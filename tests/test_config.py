"""MeasurementConfig / replace_present 的脱机测试。

字段知识集中在 :class:`MeasurementConfig`：本文件覆盖「部分更新」与「构造归一」两条契约，
不再逐字段镜像 ``Spectrometer.configure``。``configure`` 本身只在文件末尾验证一次 wiring。
"""

from __future__ import annotations

import pytest

from _fakes import FakeDevice, FakeDriver
from pyavaspec.core import (
    DriverSession,
    MeasurementConfig,
    SmoothingModel,
    Spectrometer,
    Trigger,
)
from pyavaspec.core.models import replace_present


def _cfg(**overrides: object) -> MeasurementConfig:
    values: dict[str, object] = {
        "start_pixel": 0,
        "stop_pixel": 3,
        "integration_ms": 5.0,
        "averages": 1,
    }
    values.update(overrides)
    return MeasurementConfig(**values)  # type: ignore[arg-type]


def make_spec(**device_kwargs: object) -> Spectrometer:
    device = FakeDevice(**device_kwargs)  # type: ignore[arg-type]
    session = DriverSession(driver=FakeDriver(device))  # type: ignore[arg-type]
    session.open()
    return Spectrometer(session=session)


# %% replace_present：部分更新契约


def test_replace_present_changes_only_present_fields() -> None:
    base = _cfg(averages=2, prescan=True)
    merged = replace_present(base, {"integration_ms": 12.5})
    assert merged.integration_ms == pytest.approx(12.5)
    assert merged.averages == 2
    assert merged.prescan is True


def test_replace_present_ignores_none() -> None:
    base = _cfg(integration_ms=9.0)
    assert replace_present(base, {"integration_ms": None, "averages": None}) == base


def test_replace_present_rejects_unknown_key() -> None:
    with pytest.raises(TypeError):
        replace_present(_cfg(), {"integraton_ms": 1.0})


def test_replace_present_returns_new_instance() -> None:
    base = _cfg()
    merged = replace_present(base, {})
    assert merged == base
    assert merged is not base


# %% MeasurementConfig：构造归一


def test_measurement_config_normalizes_numeric_types() -> None:
    cfg = _cfg(integration_ms=10, averages=2.7, high_res_adc=0, store_to_ram=3.9)
    assert isinstance(cfg.integration_ms, float)
    assert cfg.averages == 2
    assert cfg.high_res_adc is False
    assert cfg.store_to_ram == 3


def test_measurement_config_normalizes_smoothing_model() -> None:
    assert _cfg(smoothing_model=0).smoothing_model is SmoothingModel.AVERAGE


def test_measurement_config_rejects_non_trigger() -> None:
    with pytest.raises(TypeError):
        _cfg(trigger="software")


def test_measurement_config_default_trigger_is_software() -> None:
    assert _cfg().trigger.is_software is True
    assert isinstance(_cfg(trigger=Trigger()).trigger, Trigger)


# %% configure：wiring


def test_configure_merges_into_current_config() -> None:
    with make_spec() as spec:
        before = spec.measurement_config
        after = spec.configure(integration_ms=42.0)
        assert after.integration_ms == pytest.approx(42.0)
        assert after.averages == before.averages
        assert after.trigger == before.trigger
        assert spec.measurement_config == after


def test_configure_rejects_non_trigger_before_touching_device() -> None:
    with make_spec() as spec:
        before = spec.measurement_config
        with pytest.raises(TypeError):
            spec.configure(trigger="software")  # type: ignore[arg-type]
        assert spec.measurement_config == before
