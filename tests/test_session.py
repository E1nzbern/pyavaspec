"""features 测量会话（参考谱生命周期 + 原始谱 / 扣暗谱）的脱机测试。"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from _fakes import FakeAccess
from pyavaspec.core.errors import InvalidParameterError
from pyavaspec.core.models import Spectrum
from pyavaspec.features import (
    MeasurementSession,
    Reference,
    ReferenceConditions,
    ReferenceInvalidError,
)


def _reference(kind: str, counts: object, device: FakeAccess, **overrides: object) -> Reference:
    """按设备**当前**配置造一张参考谱（不经过设备），便于构造特定场景。"""
    cfg = device.measurement_config
    values: dict[str, object] = {
        "wavelengths": device.wavelengths,
        "counts": np.asarray(counts, dtype=np.float64),
        "timestamp_ticks": 0,
        "integration_ms": cfg.integration_ms,
        "averages": cfg.averages,
        "start_pixel": cfg.start_pixel,
        "stop_pixel": cfg.stop_pixel,
        "saturation_level": cfg.saturation_level,
    }
    values.update(overrides)
    return Reference(
        kind=kind,  # type: ignore[arg-type]
        spectrum=Spectrum(**values),  # type: ignore[arg-type]
        conditions=ReferenceConditions.from_config(cfg),
        serial=device.info.serial,
    )


# %% 原始谱永远可用 / 默认扣暗


def test_measure_without_dark_returns_original_spectrum_only() -> None:
    session = MeasurementSession(FakeAccess(counts_per_ms=1.0))

    m = session.measure()

    assert m.corrected is None
    assert m.spectrum.counts.max() > 0  # 原始谱照常可用
    assert m.status.ok is False
    assert "尚未采集 dark" in m.status.message
    assert m.status.relative_ok is False


def test_capture_dark_enables_default_correction() -> None:
    device = FakeAccess(counts_per_ms=1.0)
    session = MeasurementSession(device)

    dark = session.capture_dark(frames=2)
    m = session.measure()

    assert dark.frames == 2
    assert m.status.ok is True
    assert m.corrected is not None
    assert m.corrected.counts == pytest.approx(np.zeros(m.spectrum.size))
    assert m.spectrum.counts.max() > 0  # 原始谱没被改写


# %% 失效场景


def test_integration_change_stops_correction_but_keeps_measuring() -> None:
    device = FakeAccess(counts_per_ms=1.0, integration_ms=10.0)
    session = MeasurementSession(device)
    session.capture_dark()

    device.configure(integration_ms=20.0)
    status = session.status()
    assert status.ok is False
    assert any("积分时间" in reason for reason in status.reasons)

    m = session.measure()
    assert m.spectrum.size == device.wavelengths.size  # 照常给出原始谱
    assert m.corrected is None  # 条件漂移后不再给出无意义的差值
    assert "重新采集" in m.status.message


def test_expired_dark_still_corrects_because_conditions_match() -> None:
    device = FakeAccess(counts_per_ms=1.0)
    session = MeasurementSession(device, max_age_hours=1.0)
    session.capture_dark()
    session.dark = replace(session.dark, created=datetime.now(UTC) - timedelta(hours=2))

    m = session.measure()

    assert m.status.ok is False
    assert any("小时" in reason for reason in m.status.reasons)
    # 仅过期（条件未变）不影响算术，和商业软件一致：结果照给、提示看状态
    assert m.corrected is not None


def test_strict_policy_refuses_to_measure_with_stale_dark() -> None:
    device = FakeAccess(counts_per_ms=1.0, integration_ms=10.0)
    session = MeasurementSession(device, policy="strict")
    session.capture_dark()
    device.configure(integration_ms=20.0)
    calls = device.measure_calls

    with pytest.raises(ReferenceInvalidError):
        session.measure()

    assert device.measure_calls == calls  # 失败发生在采集之前，没白采一帧


def test_off_policy_does_not_block_but_still_reports() -> None:
    device = FakeAccess(counts_per_ms=1.0, integration_ms=10.0)
    session = MeasurementSession(device, policy="off")
    session.capture_dark()
    device.configure(integration_ms=20.0)

    m = session.measure()

    assert m.corrected is None
    assert m.status.ok is False
    assert m.status.reasons  # 状态如实记录


def test_dark_from_another_device_is_reported() -> None:
    device = FakeAccess(serial="SN-A", counts_per_ms=1.0)
    session = MeasurementSession(device)
    session.capture_dark()
    session.dark = replace(session.dark, serial="SN-B")

    status = session.status()

    assert status.ok is False
    assert any("来自设备 SN-B" in reason for reason in status.reasons)


def test_assigning_wrong_kind_is_rejected() -> None:
    device = FakeAccess(counts_per_ms=1.0)
    session = MeasurementSession(device)

    with pytest.raises(InvalidParameterError, match="dark"):
        session.dark = _reference("bright", [1.0] * 4, device)


def test_invalid_policy_is_rejected() -> None:
    with pytest.raises(InvalidParameterError):
        MeasurementSession(FakeAccess(), policy="bogus")  # type: ignore[arg-type]


# %% 相对测量


def test_transmittance_and_absorbance_need_both_references() -> None:
    session = MeasurementSession(FakeAccess(counts_per_ms=1.0))
    session.capture_dark()
    m = session.measure()

    with pytest.raises(ReferenceInvalidError):
        session.transmittance(m)
    with pytest.raises(ReferenceInvalidError):
        session.absorbance(m)


def test_transmittance_absorbance_and_reflectance() -> None:
    device = FakeAccess(counts_per_ms=1.0)  # 10 ms × 1 = 10 counts
    session = MeasurementSession(device)
    session.dark = _reference("dark", [0.0] * 4, device)
    # 亮谱需高于满量程 1%（MIN_REFERENCE_FRACTION），否则 (R - D) 判为无效
    session.bright = _reference("bright", [5000.0] * 4, device)
    m = session.measure()

    t = session.transmittance(m)
    assert t.quantity == "transmittance"
    assert t.values == pytest.approx(np.full(4, 10.0 / 5000.0))

    a = session.absorbance(m)
    assert a.quantity == "absorbance"
    assert a.values == pytest.approx(np.full(4, -np.log10(10.0 / 5000.0)))

    assert session.reflectance(m).quantity == "reflectance"


def test_incompatible_pair_blocks_relative_measurement() -> None:
    device = FakeAccess(counts_per_ms=1.0, integration_ms=10.0)
    session = MeasurementSession(device, policy="off")
    session.dark = _reference("dark", [0.0] * 4, device)

    device.configure(integration_ms=20.0)
    session.bright = _reference("bright", [500.0] * 4, device)
    m = session.measure()

    # 配对问题让比值本身失去意义，任何 policy 都不能放行
    with pytest.raises(InvalidParameterError, match="积分时间"):
        session.transmittance(m)


def test_strict_policy_rejects_expired_bright_for_relative_measurement() -> None:
    device = FakeAccess(counts_per_ms=1.0)
    session = MeasurementSession(device, policy="strict", max_age_hours=1.0)
    session.dark = _reference("dark", [0.0] * 4, device)
    session.bright = _reference("bright", [5000.0] * 4, device)
    session.bright = replace(session.bright, created=datetime.now(UTC) - timedelta(hours=2))

    m = session.measure()  # 暗谱仍有效，测量本身放行
    status = m.status
    assert status.ok is True
    assert status.relative_ok is False

    with pytest.raises(ReferenceInvalidError):
        session.transmittance(m)


# %% 多帧


def test_measure_many_returns_one_result_per_frame() -> None:
    device = FakeAccess(counts_per_ms=1.0)
    session = MeasurementSession(device)
    session.capture_dark()

    frames = list(session.measure_many(3))

    assert len(frames) == 3
    assert device.measure_calls == 4  # capture_dark 1 + 3 帧
    assert all(frame.corrected is not None for frame in frames)
    assert [frame.spectrum.sequence for frame in frames] == [2, 3, 4]
