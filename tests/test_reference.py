"""features 参考谱与相对测量的脱机测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from _fakes import FakeAccess
from pyavaspec.core.errors import InvalidParameterError
from pyavaspec.core.models import MeasurementConfig, Spectrum
from pyavaspec.features import (
    Reference,
    ReferenceConditions,
    ReferenceInvalidError,
    ReferencePair,
    capture_reference,
    check_reference,
    dark_corrected,
    relative_reflectance,
    transmittance,
)

_SATURATION = 1000


def _spectrum(counts: object, **overrides: object) -> Spectrum:
    array = np.asarray(counts, dtype=np.float64)
    size = array.size
    values: dict[str, object] = {
        "wavelengths": np.linspace(400.0, 700.0, size),
        "counts": array,
        "timestamp_ticks": 1,
        "integration_ms": 5.0,
        "averages": 1,
        "start_pixel": 0,
        "stop_pixel": size - 1,
        "saturation_level": _SATURATION,
    }
    values.update(overrides)
    return Spectrum(**values)  # type: ignore[arg-type]


def _config(**overrides: object) -> MeasurementConfig:
    values: dict[str, object] = {
        "start_pixel": 0,
        "stop_pixel": 1,
        "integration_ms": 5.0,
        "averages": 1,
        "high_res_adc": False,
    }
    values.update(overrides)
    return MeasurementConfig(**values)  # type: ignore[arg-type]


def _reference(
    counts: object = (10.0, 20.0),
    *,
    kind: str = "dark",
    serial: str = "FAKE0001",
    created: datetime | None = None,
    **overrides: object,
) -> Reference:
    return Reference(
        kind=kind,  # type: ignore[arg-type]
        spectrum=_spectrum(counts, **overrides),
        conditions=ReferenceConditions.from_config(_config()),
        serial=serial,
        created=created or datetime.now(UTC),
    )


# %% 纯计算


def test_dark_corrected_subtracts_and_floors() -> None:
    sample = _spectrum([100.0, 5.0])
    dark = _reference((10.0, 20.0)).spectrum
    result = dark_corrected(sample, dark)
    assert result.counts == pytest.approx([90.0, 0.0])
    assert sample.counts == pytest.approx([100.0, 5.0])  # 源帧不被修改


def test_dark_corrected_rejects_mismatched_integration_time() -> None:
    with pytest.raises(InvalidParameterError):
        dark_corrected(_spectrum([100.0], integration_ms=50.0), _spectrum([10.0]))


def test_transmittance_and_absorbance() -> None:
    dark = _spectrum([0.0])
    reference = _spectrum([500.0])
    sample = _spectrum([50.0])
    trans = transmittance(sample, dark, reference)
    assert trans.quantity == "transmittance"
    assert list(trans.valid) == [True]
    assert trans.values == pytest.approx([0.1])
    absorb = trans.absorbance()
    assert absorb.quantity == "absorbance"
    assert absorb.values == pytest.approx([1.0])


def test_transmittance_marks_small_reference_invalid() -> None:
    dark = _spectrum([0.0, 0.0])
    reference = _spectrum([500.0, 0.0])  # 第二像素 (R-D) = 0
    sample = _spectrum([250.0, 10.0])
    trans = transmittance(sample, dark, reference)
    assert list(trans.valid) == [True, False]
    assert np.isnan(trans.values[1])


def test_transmittance_rejects_mismatched_shape() -> None:
    with pytest.raises(InvalidParameterError):
        transmittance(_spectrum([1.0]), _spectrum([1.0, 2.0]), _spectrum([1.0]))


def test_relative_reflectance_reuses_formula() -> None:
    dark = _spectrum([0.0])
    reference = _spectrum([500.0])
    sample = _spectrum([250.0])
    result = relative_reflectance(sample, dark, reference)
    assert result.quantity == "reflectance"
    assert result.values == pytest.approx([0.5])


def test_transmittance_accepts_correctly_kinded_references() -> None:
    pair = ReferencePair(
        _reference((10.0, 10.0), kind="dark"),
        _reference((510.0, 510.0), kind="bright"),
    )
    result = pair.transmittance(_spectrum([260.0, 260.0]))
    assert result.values == pytest.approx([0.5, 0.5])
    assert pair.absorbance(_spectrum([260.0, 260.0])).quantity == "absorbance"
    assert pair.reflectance(_spectrum([260.0, 260.0])).quantity == "reflectance"


def test_transmittance_rejects_swapped_reference_kinds() -> None:
    """dark / bright 传反在数值上只是静默倒数，配对时必须直接报错"""
    dark = _reference((10.0, 10.0), kind="bright")
    bright = _reference((510.0, 510.0), kind="dark")
    with pytest.raises(InvalidParameterError, match="dark"):
        ReferencePair(dark, bright)


def test_relative_reflectance_rejects_bright_reference_as_dark() -> None:
    dark = _reference((10.0, 10.0), kind="bright")
    bright = _reference((510.0, 510.0), kind="bright")
    with pytest.raises(InvalidParameterError, match="dark"):
        ReferencePair(dark, bright)


def test_absorbance_of_non_positive_is_invalid() -> None:
    result = transmittance(_spectrum([0.0]), _spectrum([0.0]), _spectrum([500.0]))
    absorb = result.absorbance()
    assert list(absorb.valid) == [False]
    assert np.isnan(absorb.values[0])


# %% 条件与状态


def test_conditions_mismatch_puts_integration_first() -> None:
    conditions = ReferenceConditions.from_config(_config())
    reasons = conditions.mismatches(_config(integration_ms=50.0, averages=2))
    assert reasons[0].startswith("积分时间")
    assert any("平均次数" in reason for reason in reasons)


def test_conditions_detect_smoothing_model_change() -> None:
    conditions = ReferenceConditions.from_config(_config())
    reasons = conditions.mismatches(_config(smoothing_model=1))
    assert any("平滑模型" in reason for reason in reasons)


def test_status_reports_age_and_mismatch() -> None:
    old = datetime.now(UTC) - timedelta(hours=2)
    reference = _reference(created=old)
    status = reference.status(_config(), max_age_hours=1.0)
    assert status.ok is False
    assert any("小时" in reason for reason in status.reasons)
    assert "重新保存" in status.message


def test_status_ignores_age_when_none() -> None:
    old = datetime.now(UTC) - timedelta(days=10)
    reference = _reference(created=old)
    assert reference.status(_config(), max_age_hours=None).ok is True


def test_validate_raises_on_mismatch() -> None:
    reference = _reference()
    with pytest.raises(ReferenceInvalidError):
        reference.validate(_config(integration_ms=99.0))


def test_validate_allows_expired_only_when_requested() -> None:
    old = datetime.now(UTC) - timedelta(hours=2)
    reference = _reference(created=old)
    with pytest.raises(ReferenceInvalidError):
        reference.validate(_config(), max_age_hours=1.0)
    reference.validate(_config(), max_age_hours=1.0, allow_expired=True)


def test_check_reference_delegates_to_status() -> None:
    reference = _reference()
    assert check_reference(reference, _config()).ok is True


def test_status_reports_device_mismatch_first() -> None:
    reference = _reference()
    status = reference.status(_config(), serial="OTHER")
    assert status.ok is False
    assert status.reasons[0].startswith("来自设备")
    assert "OTHER" in status.reasons[0]


def test_status_without_serial_argument_skips_device_check() -> None:
    assert _reference().status(_config()).ok is True


def test_validate_rejects_device_mismatch_even_when_expired_allowed() -> None:
    reference = _reference()
    with pytest.raises(ReferenceInvalidError):
        reference.validate(_config(), serial="OTHER", allow_expired=True)


# %% 参考谱配对


def test_reference_pair_accepts_matching_references() -> None:
    pair = ReferencePair(
        _reference((10.0, 10.0), kind="dark"),
        _reference((510.0, 510.0), kind="bright"),
    )
    dark_status, bright_status = pair.statuses(_config(), serial="FAKE0001")
    assert dark_status.ok is True
    assert bright_status.ok is True


def test_reference_pair_rejects_swapped_kinds() -> None:
    with pytest.raises(InvalidParameterError, match="dark 位置"):
        ReferencePair(
            _reference((10.0, 10.0), kind="bright"),
            _reference((510.0, 510.0), kind="bright"),
        )


def test_reference_pair_rejects_different_serial() -> None:
    with pytest.raises(InvalidParameterError, match="不同设备"):
        ReferencePair(
            _reference((10.0, 10.0), kind="dark"),
            _reference((510.0, 510.0), kind="bright", serial="OTHER"),
        )


def test_reference_pair_rejects_mismatched_conditions() -> None:
    bright = Reference(
        kind="bright",
        spectrum=_spectrum((510.0, 510.0), integration_ms=9.0),
        conditions=ReferenceConditions.from_config(_config(integration_ms=9.0)),
    )
    with pytest.raises(InvalidParameterError, match="积分时间"):
        ReferencePair(_reference((10.0, 10.0), kind="dark"), bright)


# %% 持久化


def test_reference_round_trip(tmp_path) -> None:
    reference = _reference(kind="bright", created=datetime(2026, 10, 16, tzinfo=UTC))
    path = reference.save(tmp_path / "bright.json")
    loaded = Reference.load(path)
    assert loaded.kind == "bright"
    assert loaded.serial == "FAKE0001"
    assert loaded.created == reference.created
    assert loaded.conditions == reference.conditions
    assert loaded.spectrum.counts == pytest.approx(reference.spectrum.counts)


def test_reference_load_rejects_bad_format(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"format": "other/1"}', encoding="utf-8")
    with pytest.raises(InvalidParameterError):
        Reference.load(path)


# %% 采集编排


def test_capture_reference_uses_current_config() -> None:
    device = FakeAccess(counts_per_ms=1.0)
    reference = capture_reference(device, "dark", frames=3)
    assert reference.frames == 3
    assert reference.serial == "FAKE0001"
    assert reference.conditions.integration_ms == pytest.approx(10.0)
    assert device.measure_calls == 3


def test_capture_reference_rejects_bad_kind() -> None:
    with pytest.raises(InvalidParameterError):
        capture_reference(FakeAccess(), "wrong")  # type: ignore[arg-type]


def test_capture_reference_rejects_bad_frames() -> None:
    with pytest.raises(InvalidParameterError):
        capture_reference(FakeAccess(), "dark", frames=0)
