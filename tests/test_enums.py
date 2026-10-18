"""魔数转枚举（C6）的离线测试。

覆盖：四个新枚举都是 ``IntEnum``、``try_enum`` 的「已知转枚举 / 未知留 int」策略、
``Trigger`` 与 ``MeasurementConfig`` 的构造期归一化、``config_from_struct`` 的
传感器回退，以及校验改用枚举后的行为不变。
"""

from __future__ import annotations

from enum import IntEnum

import pytest

from pyavaspec._lowlevel._structs import DeviceConfigType
from pyavaspec._lowlevel._types import (
    SensorType,
    SmoothingModel,
    TriggerMode,
    TriggerSource,
    TriggerSourceType,
    try_enum,
)
from pyavaspec.core._bridge import config_from_struct
from pyavaspec.core._validate import validate_config
from pyavaspec.core.errors import InvalidParameterError
from pyavaspec.core.models import MeasurementConfig, Trigger

_NEW_ENUMS = [TriggerMode, TriggerSource, TriggerSourceType, SmoothingModel]


# %% try_enum


@pytest.mark.parametrize("enum_type", _NEW_ENUMS)
def test_new_enums_are_intenum(enum_type: type[IntEnum]) -> None:
    assert issubclass(enum_type, IntEnum)
    assert isinstance(enum_type(0), int)


def test_try_enum_known_value_returns_member() -> None:
    assert try_enum(SensorType, 22) is SensorType.HAMS11639_USB2
    assert try_enum(TriggerMode, 1) is TriggerMode.HARDWARE


def test_try_enum_member_passes_through() -> None:
    assert try_enum(SensorType, SensorType.ILX511) is SensorType.ILX511


def test_try_enum_unknown_value_stays_int() -> None:
    raw = try_enum(SensorType, 200)
    assert raw == 200
    assert not isinstance(raw, SensorType)


def test_enum_members_remain_int_compatible() -> None:
    assert TriggerMode.HARDWARE == 1
    assert TriggerMode.SOFTWARE + 1 == 1
    assert int(TriggerSourceType.LEVEL) == 1


def test_trigger_mode_values_match_dll_manual() -> None:
    assert TriggerMode.SOFTWARE == 0
    assert TriggerMode.HARDWARE == 1
    assert TriggerMode.SINGLE_SCAN == 2


# %% Trigger


def test_trigger_defaults_are_enums_and_software() -> None:
    trigger = Trigger()
    assert trigger.mode is TriggerMode.SOFTWARE
    assert trigger.source is TriggerSource.EXTERNAL
    assert trigger.source_type is TriggerSourceType.EDGE
    assert trigger.is_software is True


def test_trigger_known_int_coerces_to_enum() -> None:
    trigger = Trigger(mode=1, source=1, source_type=1)
    assert trigger.mode is TriggerMode.HARDWARE
    assert trigger.source is TriggerSource.SYNCHRONIZED
    assert trigger.source_type is TriggerSourceType.LEVEL
    assert trigger.is_software is False


def test_trigger_unknown_value_stays_int() -> None:
    trigger = Trigger(mode=9)
    assert trigger.mode == 9
    assert not isinstance(trigger.mode, TriggerMode)
    assert trigger.is_software is False


def test_single_scan_trigger_is_not_software() -> None:
    trigger = Trigger(mode=TriggerMode.SINGLE_SCAN)
    assert trigger.mode is TriggerMode.SINGLE_SCAN
    assert trigger.is_software is False


# %% MeasurementConfig / DeviceConfig


def test_measurement_config_coerces_smoothing_model() -> None:
    cfg = _cfg(smoothing_model=0)
    assert cfg.smoothing_model is SmoothingModel.AVERAGE


def test_measurement_config_keeps_unknown_smoothing_model_as_int() -> None:
    cfg = _cfg(smoothing_model=1)
    assert cfg.smoothing_model == 1
    assert not isinstance(cfg.smoothing_model, SmoothingModel)


def test_config_from_struct_coerces_known_sensor_type() -> None:
    cfg = config_from_struct(_config_struct(sensor_type=22))
    assert cfg.sensor_type is SensorType.HAMS11639_USB2


def test_config_from_struct_keeps_unknown_sensor_type_as_int() -> None:
    cfg = config_from_struct(_config_struct(sensor_type=200))
    assert cfg.sensor_type == 200
    assert not isinstance(cfg.sensor_type, SensorType)


# %% 校验（行为不变，读作枚举）


def test_store_to_ram_rejects_synchronized_trigger() -> None:
    cfg = _cfg(store_to_ram=2, trigger=Trigger(source=TriggerSource.SYNCHRONIZED))
    with pytest.raises(InvalidParameterError):
        validate_config(cfg, num_pixels=4)


def test_store_to_ram_rejects_level_trigger() -> None:
    cfg = _cfg(store_to_ram=2, trigger=Trigger(source_type=TriggerSourceType.LEVEL))
    with pytest.raises(InvalidParameterError):
        validate_config(cfg, num_pixels=4)


def test_store_to_ram_still_allowed_for_plain_int_trigger() -> None:
    # 宽松策略：原始 int 1 会被归一化成枚举，校验照样拦截同步触发
    cfg = _cfg(store_to_ram=2, trigger=Trigger(source=1))
    with pytest.raises(InvalidParameterError):
        validate_config(cfg, num_pixels=4)


def test_software_trigger_store_to_ram_is_valid() -> None:
    cfg = _cfg(store_to_ram=2)
    assert validate_config(cfg, num_pixels=4) is cfg


# %% 辅助


def _cfg(**overrides: object) -> MeasurementConfig:
    values: dict[str, object] = {
        "start_pixel": 0,
        "stop_pixel": 3,
        "integration_ms": 5.0,
        "averages": 1,
    }
    values.update(overrides)
    return MeasurementConfig(**values)  # type: ignore[arg-type]


def _config_struct(*, sensor_type: int) -> DeviceConfigType:
    struct = DeviceConfigType()
    struct.m_Detector.m_NrPixels = 4
    struct.m_Detector.m_SensorType = sensor_type
    return struct
