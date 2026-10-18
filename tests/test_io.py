"""``core.io.DeviceIO`` 板载温度换算的脱机测试。

设备没写温度标定系数时，EEPROM 里是全 0 多项式；代入会算出 0 ℃ 这种"看起来正常"
的假温度，所以 ``DeviceIO`` 必须直接报错，而不是返回 0.0。
"""

from __future__ import annotations

import pytest

from pyavaspec.core.errors import InvalidParameterError
from pyavaspec.core.io import DeviceIO


class _AnalogPort:
    """最小 IOPort 替身：只实现板载温度换算需要的模拟输入。"""

    def __init__(self, volts: float) -> None:
        self._volts = volts

    def read_analog_in(self, channel: int) -> float:
        return self._volts


def test_board_temperature_rejects_missing_fit() -> None:
    io = DeviceIO(_AnalogPort(1.978), temperature_fit=None)  # type: ignore[arg-type]

    with pytest.raises(InvalidParameterError, match="没有温度标定"):
        io.board_temperature()


def test_board_temperature_rejects_unconnected_channel() -> None:
    # 65.535 V 是驱动约定的"未接线"哨兵值
    io = DeviceIO(_AnalogPort(65.535), temperature_fit=(1.0, 0.0, 0.0, 0.0, 0.0))  # type: ignore[arg-type]

    with pytest.raises(InvalidParameterError, match="无法换算温度"):
        io.board_temperature()
