"""数字、模拟 IO 和板载温度传感器

通过 ``Spectrometer.io`` 访问

数字引脚 0-5；模拟输入 0-7，通道 0 为板载温度；模拟输出 0-1
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._validate import (
    ANALOG_IN_MAX,
    ANALOG_IN_MIN,
    ANALOG_OUT_MAX,
    ANALOG_OUT_MIN,
    PIN_MAX,
    PIN_MIN,
    TEMP_CHANNEL,
    UNCONNECTED_SENTINEL,
    validate_analog_in_channel,
    validate_analog_out_port,
    validate_pin,
    validate_pwm,
)
from .errors import InvalidParameterError

if TYPE_CHECKING:
    from ._ports import IOPort

__all__ = ["DeviceIO"]


class DeviceIO:
    """已打开设备的 IO API

    依赖 :class:`~pyavaspec.core._ports.IOPort`，句柄和返回码映射都在 port
    实现 :class:`~pyavaspec.core._driver.BoundDevice` 里
    """

    PIN_MIN = PIN_MIN
    PIN_MAX = PIN_MAX
    ANALOG_IN_MIN = ANALOG_IN_MIN
    ANALOG_IN_MAX = ANALOG_IN_MAX
    ANALOG_OUT_MIN = ANALOG_OUT_MIN
    ANALOG_OUT_MAX = ANALOG_OUT_MAX
    TEMP_CHANNEL = TEMP_CHANNEL
    UNCONNECTED_SENTINEL = UNCONNECTED_SENTINEL

    def __init__(
        self,
        port: IOPort,
        *,
        temperature_fit: tuple[float, ...] | None = None,
    ) -> None:
        self._port = port
        self._temperature_fit = temperature_fit

    def digital_in(self, pin: int) -> bool:
        """读数字输入电平"""
        value = validate_pin(pin)
        return bool(self._port.read_dig_in(value))

    def digital_out(self, pin: int, value: bool) -> None:
        """设置数字输出电平"""
        port = validate_pin(pin)
        self._port.write_dig_out(port, 1 if value else 0)

    def analog_in(self, channel: int) -> float:
        """读模拟输入电压 V，通道 0 为板载温度传感器"""
        ch = validate_analog_in_channel(channel)
        return float(self._port.read_analog_in(ch))

    def analog_out(self, port: int, volts: float) -> None:
        """设置模拟输出电压 V"""
        p = validate_analog_out_port(port)
        value = float(volts)
        if value < 0.0:
            raise InvalidParameterError(f"模拟输出电压不能为负：{value}")
        self._port.write_analog_out(p, value)

    def pwm_out(self, port: int, frequency_hz: int, duty_percent: int) -> None:
        """PWM 输出。需要硬件支持，不支持时会抛 ``OperationNotSupportedError``"""
        p = validate_pin(port)
        freq, duty = validate_pwm(frequency_hz, duty_percent)
        self._port.write_pwm(p, freq, duty)

    def board_temperature(self, channel: int = TEMP_CHANNEL) -> float:
        """板载温度（℃）：把通道电压代入配置里的温度多项式进行计算"""
        volts = self.analog_in(channel)
        if volts >= UNCONNECTED_SENTINEL - 1e-3:
            raise InvalidParameterError(f"通道 {channel} 返回 {volts:.3f} V，无法换算温度")
        fit = self._temperature_fit
        if not fit:
            raise InvalidParameterError("设备配置里没有温度标定系数，无法换算温度")
        return float(sum(c * volts**i for i, c in enumerate(fit)))
