"""`avaspecx64.dll` 的 ctypes 绑定，静态类型定义位于 :file:`_binding.pyi`。

- 句柄 `AvsHandle` = `int`；时间戳单位 10 µs ；积分时间单位 ms ；模拟输入单位 V
- 返回码含义见 :class:`._errors.ErrCode`
"""

from __future__ import annotations

import ctypes
import os
from collections.abc import Callable
from typing import Any

from ._constants import MAX_PIXELS, VERSION_LEN
from ._loader import load_library
from ._structs import AvsIdentityType, DeviceConfigType, MeasConfigType

_P = ctypes.POINTER

AvsHandle = ctypes.c_int  # typedef int AvsHandle
SensorType = ctypes.c_ubyte  # typedef unsigned char SensorType
uint8 = ctypes.c_ubyte  # typedef uint8_t uint8
uint16 = ctypes.c_uint16  # typedef uint16_t uint16
uint32 = ctypes.c_uint32  # typedef uint32_t uint32
int32 = ctypes.c_int32  # typedef int32_t int32


class _AvaSpecxNative:
    """`avaspecx64.dll` 绑定"""

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        loader: Callable[[str], Any] | None = None,
    ) -> None:
        self.path: str = os.fspath(path)
        self.lib: Any = (loader or load_library)(self.path)
        self._setup_bindings()

    def _setup_bindings(self) -> None:
        """绑定 `AVS_*` 函数原型"""
        lib = self.lib

        # %% 会话
        self._Init = lib.AVS_Init
        self._Init.restype = ctypes.c_int
        self._Init.argtypes = [ctypes.c_short]

        self._Done = lib.AVS_Done
        self._Done.restype = ctypes.c_int
        self._Done.argtypes = []

        self._UpdateUSBDevices = lib.AVS_UpdateUSBDevices
        self._UpdateUSBDevices.restype = ctypes.c_int
        self._UpdateUSBDevices.argtypes = []

        # %% 设备枚举 / 激活
        self._GetList = lib.AVS_GetList
        self._GetList.restype = ctypes.c_int
        self._GetList.argtypes = [uint32, _P(uint32), _P(AvsIdentityType)]

        self._Activate = lib.AVS_Activate
        self._Activate.restype = AvsHandle
        self._Activate.argtypes = [_P(AvsIdentityType)]

        self._Deactivate = lib.AVS_Deactivate
        self._Deactivate.restype = ctypes.c_bool  # bool
        self._Deactivate.argtypes = [AvsHandle]

        # %% 版本信息
        # GetVersionInfo 需要 handle
        # 缓冲头文件写的是 unsigned char*，用 c_char*N 以兼容 create_string_buffer
        self._GetVersionInfo = lib.AVS_GetVersionInfo
        self._GetVersionInfo.restype = ctypes.c_int
        self._GetVersionInfo.argtypes = [
            AvsHandle,
            ctypes.c_char * VERSION_LEN,
            ctypes.c_char * VERSION_LEN,
            ctypes.c_char * VERSION_LEN,
        ]

        # GetDLLVersion 不需要 handle
        self._GetDLLVersion = lib.AVS_GetDLLVersion
        self._GetDLLVersion.restype = ctypes.c_int
        self._GetDLLVersion.argtypes = [ctypes.c_char * 64]

        # %% 设备信息
        self._GetNumPixels = lib.AVS_GetNumPixels
        self._GetNumPixels.restype = ctypes.c_int
        self._GetNumPixels.argtypes = [AvsHandle, _P(uint16)]

        self._GetLambda = lib.AVS_GetLambda
        self._GetLambda.restype = ctypes.c_int
        self._GetLambda.argtypes = [AvsHandle, _P(ctypes.c_double * MAX_PIXELS)]

        self._UseHighResAdc = lib.AVS_UseHighResAdc
        self._UseHighResAdc.restype = ctypes.c_int
        self._UseHighResAdc.argtypes = [AvsHandle, ctypes.c_bool]

        # %% 采集
        self._PrepareMeasure = lib.AVS_PrepareMeasure
        self._PrepareMeasure.restype = ctypes.c_int
        self._PrepareMeasure.argtypes = [AvsHandle, _P(MeasConfigType)]

        # a_Nmsr 是有符号 short
        # 1=一帧、-1=连续、StoreToRam 用 1
        # 第二参是 HWND，脚本场景传 None，用 void* 表示
        self._Measure = lib.AVS_Measure
        self._Measure.restype = ctypes.c_int
        self._Measure.argtypes = [AvsHandle, ctypes.c_void_p, ctypes.c_short]

        self._StopMeasure = lib.AVS_StopMeasure
        self._StopMeasure.restype = ctypes.c_int
        self._StopMeasure.argtypes = [AvsHandle]

        # 非头文件导出，签名未验证，实测以 (handle) 调用会访问违例，慎用。
        self._ForceStopMeas = lib.AVS_ForceStopMeas
        self._ForceStopMeas.restype = ctypes.c_int
        self._ForceStopMeas.argtypes = [AvsHandle]

        self._PollScan = lib.AVS_PollScan
        self._PollScan.restype = ctypes.c_int
        self._PollScan.argtypes = [AvsHandle]

        self._GetScopeData = lib.AVS_GetScopeData
        self._GetScopeData.restype = ctypes.c_int
        self._GetScopeData.argtypes = [
            AvsHandle,
            _P(uint32),
            _P(ctypes.c_double * MAX_PIXELS),
        ]

        # %% 配置读写（DeviceConfigType 63484 B）
        self._GetParameter = lib.AVS_GetParameter
        self._GetParameter.restype = ctypes.c_int
        self._GetParameter.argtypes = [
            AvsHandle,
            uint32,
            _P(uint32),
            _P(DeviceConfigType),
        ]

        self._SetParameter = lib.AVS_SetParameter
        self._SetParameter.restype = ctypes.c_int
        self._SetParameter.argtypes = [AvsHandle, _P(DeviceConfigType)]

        # %% 数据变体 / 辅助方法
        self._GetSaturatedPixels = lib.AVS_GetSaturatedPixels
        self._GetSaturatedPixels.restype = ctypes.c_int
        self._GetSaturatedPixels.argtypes = [AvsHandle, _P(uint8 * MAX_PIXELS)]

        # 非头文件导出，第二个参数是 void*，实测输出 uint32，调用方只关心像素数
        self._GetMeasPixels = lib.AVS_GetMeasPixels
        self._GetMeasPixels.restype = ctypes.c_int
        self._GetMeasPixels.argtypes = [AvsHandle, ctypes.c_void_p]

        self._GetAnalogIn = lib.AVS_GetAnalogIn
        self._GetAnalogIn.restype = ctypes.c_int
        self._GetAnalogIn.argtypes = [AvsHandle, uint8, _P(ctypes.c_float)]

        # %% Digital IO
        self._GetDigIn = lib.AVS_GetDigIn
        self._GetDigIn.restype = ctypes.c_int
        self._GetDigIn.argtypes = [AvsHandle, uint8, _P(uint8)]

        self._SetDigOut = lib.AVS_SetDigOut
        self._SetDigOut.restype = ctypes.c_int
        self._SetDigOut.argtypes = [AvsHandle, uint8, uint8]

        self._SetPrescanMode = lib.AVS_SetPrescanMode
        self._SetPrescanMode.restype = ctypes.c_int
        self._SetPrescanMode.argtypes = [AvsHandle, ctypes.c_bool]

        # %% 原始数据 / CRC
        self._GetRawScopeDataCRC = lib.AVS_GetRawScopeDataCRC
        self._GetRawScopeDataCRC.restype = ctypes.c_int
        self._GetRawScopeDataCRC.argtypes = [
            AvsHandle,
            _P(uint32),
            _P(uint16),
            _P(uint32),
            _P(uint16),
            _P(uint32 * MAX_PIXELS),
        ]

        self._CheckCRC = lib.AVS_CheckCRC
        self._CheckCRC.restype = ctypes.c_bool
        self._CheckCRC.argtypes = [
            uint32,
            uint16,
            ctypes.c_bool,
            _P(uint32 * MAX_PIXELS),
        ]

        self._EnableCRC = lib.AVS_EnableCRC
        self._EnableCRC.restype = ctypes.c_int
        self._EnableCRC.argtypes = [AvsHandle, ctypes.c_bool]

        # %% 杂散光抑制（纯软件）
        self._SuppressStrayLight = lib.AVS_SuppressStrayLight
        self._SuppressStrayLight.restype = ctypes.c_int
        self._SuppressStrayLight.argtypes = [
            AvsHandle,
            ctypes.c_float,
            _P(ctypes.c_double * MAX_PIXELS),
            _P(ctypes.c_double * MAX_PIXELS),
        ]

        # %% 模拟输出 / PWM / 同步 / 灵敏度
        # 需要硬件支持
        self._SetAnalogOut = lib.AVS_SetAnalogOut
        self._SetAnalogOut.restype = ctypes.c_int
        self._SetAnalogOut.argtypes = [AvsHandle, uint8, ctypes.c_float]

        self._SetPwmOut = lib.AVS_SetPwmOut
        self._SetPwmOut.restype = ctypes.c_int
        self._SetPwmOut.argtypes = [AvsHandle, uint8, uint32, uint8]

        self._SetSyncMode = lib.AVS_SetSyncMode
        self._SetSyncMode.restype = ctypes.c_int
        self._SetSyncMode.argtypes = [AvsHandle, uint8]

        self._SetSensitivityMode = lib.AVS_SetSensitivityMode
        self._SetSensitivityMode.restype = ctypes.c_int
        self._SetSensitivityMode.argtypes = [AvsHandle, uint32]

        # 返回 -16 表示设备正在重启，属预期而非错误。
        self._ResetDevice = lib.AVS_ResetDevice
        self._ResetDevice.restype = ctypes.c_int
        self._ResetDevice.argtypes = [AvsHandle]

        # %% 额外只读查询
        # 非头文件导出
        # 第二个参数是传感器类型选择，不是缓冲长度
        self._GetDetectorName = lib.AVS_GetDetectorName
        self._GetDetectorName.restype = ctypes.c_int
        self._GetDetectorName.argtypes = [AvsHandle, uint32, ctypes.c_char * 256]

        self._GetDeviceType = lib.AVS_GetDeviceType
        self._GetDeviceType.restype = ctypes.c_int
        self._GetDeviceType.argtypes = [AvsHandle, _P(int32)]

        self._GetStatusBySerial = lib.AVS_GetStatusBySerial
        self._GetStatusBySerial.restype = ctypes.c_int
        self._GetStatusBySerial.argtypes = [ctypes.c_char_p, _P(uint8)]
