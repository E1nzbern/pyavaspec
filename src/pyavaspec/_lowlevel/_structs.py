"""头文件定义的结构体，实际上全部 `_pack_ = 1`"""

from __future__ import annotations

import ctypes
from ctypes import (
    Structure,
    c_bool,
    c_char,
    c_double,
    c_float,
    c_int16,
    c_int32,
    c_uint8,
    c_uint16,
    c_uint32,
)

from ._constants import AVS_SERIAL_LEN, DEVICE_CONFIG_LEN, USER_ID_LEN

# %% 基础子结构体


class SmoothingType(Structure):
    _pack_ = 1
    _fields_ = [
        ("m_SmoothPix", c_uint16),
        ("m_SmoothModel", c_uint8),
    ]


class DarkCorrectionType(Structure):
    _pack_ = 1
    _fields_ = [
        ("m_Enable", c_uint8),
        ("m_ForgetPercentage", c_uint8),
    ]


class TriggerType(Structure):
    _pack_ = 1
    _fields_ = [
        ("m_Mode", c_uint8),
        ("m_Source", c_uint8),
        ("m_SourceType", c_uint8),
    ]


class ControlSettingsType(Structure):
    _pack_ = 1
    _fields_ = [
        ("m_StrobeControl", c_uint16),
        ("m_LaserDelay", c_uint32),
        ("m_LaserWidth", c_uint32),
        ("m_LaserWaveLength", c_float),
        ("m_StoreToRam", c_uint16),
    ]


# %% 标定 / 探测 / 温度 / 控制


class SpectrumCalibrationType(Structure):
    _pack_ = 1
    _fields_ = [
        ("m_Smoothing", SmoothingType),
        ("m_CalInttime", c_float),
        ("m_aCalibConvers", c_float * 4096),
    ]


class SpectrumCorrectionType(Structure):
    _pack_ = 1
    _fields_ = [
        ("m_aSpectrumCorrect", c_float * 4096),
    ]


class IrradianceType(Structure):
    _pack_ = 1
    _fields_ = [
        ("m_IntensityCalib", SpectrumCalibrationType),
        ("m_CalibrationType", c_uint8),
        ("m_FiberDiameter", c_uint32),
    ]


class DetectorType(Structure):
    _pack_ = 1
    _fields_ = [
        ("m_SensorType", c_uint8),
        ("m_NrPixels", c_uint16),
        ("m_aFit", c_float * 5),  # 波长标定多项式 a0..a4
        ("m_NLEnable", c_bool),
        ("m_aNLCorrect", c_double * 8),
        ("m_aLowNLCounts", c_double),
        ("m_aHighNLCounts", c_double),
        ("m_Gain", c_float * 2),
        ("m_Reserved", c_float),
        ("m_Offset", c_float * 2),
        ("m_ExtOffset", c_float),
        ("m_DefectivePixels", c_uint16 * 30),
    ]


class TempSensorType(Structure):
    _pack_ = 1
    _fields_ = [
        ("m_aFit", c_float * 5),
    ]


class TecControlType(Structure):
    _pack_ = 1
    _fields_ = [
        ("m_Enable", c_bool),
        ("m_Setpoint", c_float),
        ("m_aFit", c_float * 2),
    ]


class ProcessControlType(Structure):
    _pack_ = 1
    _fields_ = [
        ("m_AnalogLow", c_float * 2),
        ("m_AnalogHigh", c_float * 2),
        ("m_DigitalLow", c_float * 10),
        ("m_DigitalHigh", c_float * 10),
    ]


class EthernetSettingsType(Structure):
    _pack_ = 1
    _fields_ = [
        ("m_IpAddr", c_uint32),
        ("m_NetMask", c_uint32),
        ("m_Gateway", c_uint32),
        ("m_DhcpEnabled", c_uint8),
        ("m_TcpPort", c_uint16),
        ("m_LinkStatus", c_uint8),
        ("m_ClientIdType", c_uint8),
        ("m_ClientIdCustom", c_char * 32),
        ("m_MeasurementDataPortKey", c_uint16),
        ("m_MeasurementDataPort", c_uint16),
        ("m_Reserved", c_uint8 * 75),
    ]


class OemDataType(Structure):
    _pack_ = 1
    _fields_ = [
        ("data", c_uint8 * 4096),
    ]


# %% 测量配置（MeasConfigType 的嵌套组成）


class MeasConfigType(Structure):
    """测量配置，固定 41 字节"""

    _pack_ = 1
    _fields_ = [
        ("m_StartPixel", c_uint16),
        ("m_StopPixel", c_uint16),
        ("m_IntegrationTime", c_float),  # ms
        ("m_IntegrationDelay", c_uint32),  # FPGA tick（48 MHz ≈ 20.83 ns）
        ("m_NrAverages", c_uint32),
        ("m_CorDynDark", DarkCorrectionType),
        ("m_Smoothing", SmoothingType),
        ("m_SaturationDetection", c_uint8),
        ("m_Trigger", TriggerType),
        ("m_Control", ControlSettingsType),
    ]


class StandaloneType(Structure):
    _pack_ = 1
    _fields_ = [
        ("m_Enable", c_bool),
        ("m_Meas", MeasConfigType),
        ("m_Nmsr", c_int16),
    ]


class DynamicStorageType(Structure):
    _pack_ = 1
    _fields_ = [
        ("m_Nmsr", c_int32),
        ("m_Reserved", c_uint8 * 8),
    ]


# %% 设备完整参数（EEPROM 镜像）


class DeviceConfigType(Structure):
    """设备完整参数，固定 63484 字节

    慎重使用！写入前必须备份并回读校验，大部分字段没有在真机验证过。
    """

    _pack_ = 1
    _fields_ = [
        ("m_Len", c_uint16),
        ("m_ConfigVersion", c_uint16),
        ("m_aUserFriendlyId", c_char * USER_ID_LEN),
        ("m_Detector", DetectorType),
        ("m_Irradiance", IrradianceType),
        ("m_Reflectance", SpectrumCalibrationType),
        ("m_SpectrumCorrect", SpectrumCorrectionType),
        ("m_StandAlone", StandaloneType),
        ("m_DynamicStorage", DynamicStorageType),
        ("m_Temperature", TempSensorType * 3),
        ("m_TecControl", TecControlType),
        ("m_ProcessControl", ProcessControlType),
        ("m_EthernetSettings", EthernetSettingsType),
        ("m_MessageAckDisable", c_bool),
        ("m_IncludeCRC", c_bool),
        ("m_aReserved", c_uint8 * 9606),
        ("m_OemData", OemDataType),
    ]


# %% 身份 / 状态


class AvsIdentityType(Structure):
    """设备身份信息，固定 75 字节

    DLL 实际上 `AvsIdentityType` stride = 75、`Status` 位于 offset 74、占 1 字节，
    故这里用 `c_uint8`；用 `c_int` 会让结构体变成 78 字节并让多设备枚举错位
    """

    _pack_ = 1
    _fields_ = [
        ("SerialNumber", c_char * AVS_SERIAL_LEN),
        ("UserFriendlyName", c_char * USER_ID_LEN),
        ("Status", c_uint8),
    ]


class DstrStatusType(Structure):
    """StoreToRam 状态，`AVS_GetDstrStatus` 用需要硬件支持"""

    _pack_ = 1
    _fields_ = [
        ("m_TotalScans", c_uint32),
        ("m_UsedScans", c_uint32),
        ("m_Flags", c_uint32),
        ("m_IsStopEvent", c_uint8),
        ("m_IsOverflowEvent", c_uint8),
        ("m_IsInternalErrorEvent", c_uint8),
        ("m_Reserved", c_uint8),
    ]


class BroadcastAnswerType(Structure):
    """以太网广播应答，`AVS_UpdateETHDevices` 用"""

    _pack_ = 1
    _fields_ = [
        ("InterfaceType", c_uint8),
        ("serial", c_uint8 * 10),
        ("port", c_uint16),
        ("status", c_uint8),
        ("RemoteHostIp", c_uint32),
        ("LocalIp", c_uint32),
        ("reserved", c_uint8 * 4),
    ]


# %% ABI 断言，在版本 9.14.0.20 测试过

assert ctypes.sizeof(AvsIdentityType) == 75, ctypes.sizeof(AvsIdentityType)
assert AvsIdentityType.Status.offset == 74, AvsIdentityType.Status.offset
assert ctypes.sizeof(MeasConfigType) == 41, ctypes.sizeof(MeasConfigType)
assert ctypes.sizeof(DstrStatusType) == 16, ctypes.sizeof(DstrStatusType)
assert ctypes.sizeof(BroadcastAnswerType) == 26, ctypes.sizeof(BroadcastAnswerType)
assert ctypes.sizeof(DeviceConfigType) == DEVICE_CONFIG_LEN, ctypes.sizeof(DeviceConfigType)

# 嵌套字段偏移量
_DEVICE_CONFIG_ANCHORS = {
    "m_Detector": 68,
    "m_Irradiance": 256,
    "m_Reflectance": 16652,
    "m_SpectrumCorrect": 33043,
    "m_StandAlone": 49427,
    "m_DynamicStorage": 49471,
    "m_Temperature": 49483,
    "m_TecControl": 49543,
    "m_ProcessControl": 49556,
    "m_EthernetSettings": 49652,
    "m_MessageAckDisable": 49780,
    "m_IncludeCRC": 49781,
    "m_aReserved": 49782,
    "m_OemData": 59388,
}

for _name, _expected in _DEVICE_CONFIG_ANCHORS.items():
    _actual = getattr(DeviceConfigType, _name).offset
    assert _actual == _expected, f"{_name} 偏移应为 {_expected}，实际 {_actual}"
