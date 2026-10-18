"""设备参数枚举"""

from enum import IntEnum


class DeviceStatus(IntEnum):
    """`AvsIdentityType.Status` 设备在线、被占用状态"""

    UNKNOWN = 0
    USB_AVAILABLE = 1
    USB_IN_USE_BY_APPLICATION = 2
    USB_IN_USE_BY_OTHER = 3
    ETH_AVAILABLE = 4
    ETH_IN_USE_BY_APPLICATION = 5
    ETH_IN_USE_BY_OTHER = 6
    ETH_ALREADY_IN_USE_USB = 7


class InterfaceType(IntEnum):
    """设备接口类型"""

    RS232 = 0
    USB5216 = 1
    USBMINI = 2
    USB7010 = 3
    ETH7010 = 4
    USB7007 = 5


class DeviceType(IntEnum):
    """设备类型"""

    TYPE_UNKNOWN = 0
    TYPE_AS5216 = 1
    TYPE_ASMINI = 2
    TYPE_AS7010 = 3
    TYPE_AS7007 = 4


class Port(IntEnum):
    """设备端口类型选择"""

    ALL = -1
    USB = 0
    ETH = 256


class SensorType(IntEnum):
    """探测器型号

    `0` 和 `22` 都返回 `"HAMS11639"`、`19` 和 `20` 都返回 `"undefined"`，用后缀区分
    """

    HAMS11639 = 0
    HAMS8378_256 = 1
    HAMS8378_1024 = 2
    ILX554 = 3
    HAMS9201 = 4
    TCD1304 = 5
    TSL1301 = 6
    TSL1401 = 7
    HAMS8378_512 = 8
    HAMS9840 = 9
    ILX511 = 10
    HAMS10420_11850 = 11
    HAMS11071_2048x64 = 12
    HAMS7031_11501 = 13
    HAMS7031_1024x58 = 14
    HAMS11071_2048x16 = 15
    HAMS11155 = 16
    SU256LSB = 17
    SU512LDB = 18
    UNDEFINED_19 = 19
    UNDEFINED_20 = 20
    HAMS11638 = 21
    HAMS11639_USB2 = 22
    HAMS12443 = 23
    HAMG9208_512 = 24


class TriggerMode(IntEnum):
    """`MeasConfigType.m_Trigger.m_Mode` 触发方式

    - ``SOFTWARE``：``AVS_Measure()`` 后立即开始；
    - ``HARDWARE``：等待外部触发（外部、边沿触发时为 pin 6 上升沿）后开始；
    - ``SINGLE_SCAN``：每次触发只采一帧，仅 AS7010 / Mini 支持。

    前两项已在 AvaSpec-2048-USB2 上验证，硬件模式下没有触发信号时
    ``poll_scan`` 不会就绪。
    """

    SOFTWARE = 0
    HARDWARE = 1
    SINGLE_SCAN = 2


class TriggerSource(IntEnum):
    """`MeasConfigType.m_Trigger.m_Source` 触发源

    ``SYNCHRONIZED`` 用于多台光谱仪的 SYNC 同步测量。
    """

    EXTERNAL = 0
    SYNCHRONIZED = 1


class TriggerSourceType(IntEnum):
    """`MeasConfigType.m_Trigger.m_SourceType` 触发信号类型"""

    EDGE = 0
    LEVEL = 1


class SmoothingModel(IntEnum):
    """`MeasConfigType.m_Smoothing.m_SmoothModel` 平滑模型

    官方手册目前只定义模型 ``0``（窗口内平均）。
    """

    AVERAGE = 0


# 重复型号
_SENSOR_DISPLAY_OVERRIDES = {
    0: "HAMS11639",
    22: "HAMS11639",
    19: "undefined",
    20: "undefined",
}


def display_name(value: int | SensorType) -> str:
    """返回探测器型号的显示名"""
    code = int(value)
    if code in _SENSOR_DISPLAY_OVERRIDES:
        return _SENSOR_DISPLAY_OVERRIDES[code]
    try:
        return SensorType(code).name
    except ValueError:
        return str(code)


def try_enum[EnumT: IntEnum](enum_type: type[EnumT], raw: int | EnumT) -> EnumT | int:
    """尝试将返回的 int 转换为已知的枚举类型，失败则原样返回"""
    if isinstance(raw, enum_type):
        return raw
    try:
        return enum_type(raw)
    except ValueError:
        return raw
