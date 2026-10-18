"""参数校验

提前拦截 DLL 会报错的调用

已知 DLL 错误码：
像素范围 -10、积分时间 -11、非法组合 -12、平均/RAM -111、SYNC/RAM -112、Level/RAM -113。
"""

from __future__ import annotations

from .._lowlevel._types import TriggerSource, TriggerSourceType
from .errors import InvalidParameterError
from .models import MeasurementConfig

__all__ = [
    "ANALOG_IN_MAX",
    "ANALOG_IN_MIN",
    "ANALOG_OUT_MAX",
    "ANALOG_OUT_MIN",
    "MAX_INTEGRATION_MS",
    "PIN_MAX",
    "PIN_MIN",
    "STRAY_LIGHT_MAX",
    "STRAY_LIGHT_MIN",
    "TEMP_CHANNEL",
    "UNCONNECTED_SENTINEL",
    "validate_analog_in_channel",
    "validate_analog_out_port",
    "validate_config",
    "validate_pin",
    "validate_pwm",
    "validate_stray_light_factor",
]

MAX_INTEGRATION_MS = 600_000.0

PIN_MIN, PIN_MAX = 0, 5
ANALOG_IN_MIN, ANALOG_IN_MAX = 0, 7
ANALOG_OUT_MIN, ANALOG_OUT_MAX = 0, 1
TEMP_CHANNEL = 0
#: 杂散光抑制系数的有效范围，越界时驱动返回 -144
STRAY_LIGHT_MIN, STRAY_LIGHT_MAX = 0.0, 2.0
#: 模拟输入未连接时的返回值（V）
UNCONNECTED_SENTINEL = 65.535


def validate_config(cfg: MeasurementConfig, num_pixels: int) -> MeasurementConfig:
    """校验一份完整的测量配置"""
    n = int(num_pixels)
    if n <= 0:
        raise InvalidParameterError(f"设备像素数非法：{n}")
    if not (0 <= cfg.start_pixel <= cfg.stop_pixel <= n - 1):
        raise InvalidParameterError(
            f"像素范围非法：({cfg.start_pixel}, {cfg.stop_pixel})，有效范围 0..{n - 1}"
        )
    if not (0.0 < cfg.integration_ms <= MAX_INTEGRATION_MS):
        raise InvalidParameterError(
            f"积分时间需在 (0, {MAX_INTEGRATION_MS:g}] ms，收到 {cfg.integration_ms}"
        )
    if cfg.integration_delay_ticks < 0:
        raise InvalidParameterError("integration_delay_ticks 不能为负")
    if cfg.averages < 1:
        raise InvalidParameterError(f"平均次数必须 >= 1，收到 {cfg.averages}")
    if cfg.smoothing_pixels < 0:
        raise InvalidParameterError("smoothing_pixels 不能为负")
    if not (0 <= cfg.forget_percentage <= 0xFF):
        raise InvalidParameterError("forget_percentage 需在 0..255")
    if not (0 <= cfg.store_to_ram <= 0xFFFF):
        raise InvalidParameterError(f"store_to_ram 超出 uint16 范围：{cfg.store_to_ram}")
    if cfg.store_to_ram > 0:
        if cfg.averages != 1:
            raise InvalidParameterError("StoreToRam 与平均次数不兼容，请设 averages=1")
        if cfg.trigger.source == TriggerSource.SYNCHRONIZED:
            raise InvalidParameterError("StoreToRam 与 SYNC 同步不兼容")
        if cfg.trigger.source_type == TriggerSourceType.LEVEL:
            raise InvalidParameterError("StoreToRam 与 Level 触发不兼容")
    return cfg


def validate_pin(pin: int) -> int:
    value = int(pin)
    if not (PIN_MIN <= value <= PIN_MAX):
        raise InvalidParameterError(f"数字 IO 引脚序号需在 {PIN_MIN}..{PIN_MAX}，收到 {value}")
    return value


def validate_analog_in_channel(channel: int) -> int:
    value = int(channel)
    if not (ANALOG_IN_MIN <= value <= ANALOG_IN_MAX):
        raise InvalidParameterError(
            f"模拟输入通道序号需在 {ANALOG_IN_MIN}..{ANALOG_IN_MAX}，收到 {value}"
        )
    return value


def validate_analog_out_port(port: int) -> int:
    value = int(port)
    if not (ANALOG_OUT_MIN <= value <= ANALOG_OUT_MAX):
        raise InvalidParameterError(
            f"模拟输出端口序号需在 {ANALOG_OUT_MIN}..{ANALOG_OUT_MAX}，收到 {value}"
        )
    return value


def validate_stray_light_factor(multi_factor: float) -> float:
    """校验杂散光抑制系数，有效范围 0.0..2.0"""
    value = float(multi_factor)
    if not (STRAY_LIGHT_MIN <= value <= STRAY_LIGHT_MAX):
        raise InvalidParameterError(
            f"杂散光抑制系数需在 {STRAY_LIGHT_MIN:g}..{STRAY_LIGHT_MAX:g}，收到 {value}"
        )
    return value


def validate_pwm(frequency_hz: int, duty_percent: int) -> tuple[int, int]:
    freq = int(frequency_hz)
    if freq <= 0:
        raise InvalidParameterError(f"PWM 频率需为正整数，收到 {freq}")
    duty = int(duty_percent)
    if not (0 <= duty <= 100):
        raise InvalidParameterError(f"PWM 占空比需在 0..100，收到 {duty}")
    return freq, duty
