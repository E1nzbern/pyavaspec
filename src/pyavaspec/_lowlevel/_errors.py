"""错误码枚举和底层异常

`AVS_*` 的返回码约定 `<0` 表示失败
:func:`check` 将返回码转成 :class:`AvsError`
"""

from __future__ import annotations

from enum import IntEnum


class ErrCode(IntEnum):
    """`AVS_*` 返回码
    `ERR_SUCCESS=0`，其余负值表示失败。
    """

    ERR_SUCCESS = 0
    ERR_INVALID_PARAMETER = -1
    ERR_OPERATION_NOT_SUPPORTED = -2
    ERR_DEVICE_NOT_FOUND = -3
    ERR_INVALID_DEVICE_ID = -4  # 头文件未定义
    ERR_OPERATION_PENDING = -5
    ERR_TIMEOUT = -6
    ERR_RESERVED_7 = -7  # 保留
    ERR_INVALID_MEAS_DATA = -8
    ERR_INVALID_SIZE = -9
    ERR_INVALID_PIXEL_RANGE = -10
    ERR_INVALID_INT_TIME = -11
    ERR_INVALID_COMBINATION = -12
    ERR_RESERVED_13 = -13  # 保留
    ERR_NO_MEAS_BUFFER_AVAIL = -14
    ERR_UNKNOWN = -15
    ERR_COMMUNICATION = -16
    ERR_NO_SPECTRA_IN_RAM = -17
    ERR_INVALID_DLL_VERSION = -18
    ERR_NO_MEMORY = -19
    ERR_DLL_INITIALISATION = -20
    ERR_INVALID_STATE = -21

    ERR_INVALID_REPLY = -22
    ERR_ACCESS = -24
    ERR_INTERNAL_READ = -25
    ERR_INTERNAL_WRITE = -26
    ERR_ETHCONN_REUSE = -27
    ERR_INVALID_DEVICE_TYPE = -28
    ERR_SECURE_CFG_NOT_READ = -29
    ERR_UNEXPECTED_MEAS_RESPONSE = -30

    ERR_INVALID_PARAMETER_NR_PIXEL = -100
    ERR_INVALID_PARAMETER_ADC_GAIN = -101
    ERR_INVALID_PARAMETER_ADC_OFFSET = -102
    ERR_INVALID_MEASPARAM_AVG_SAT2 = -110
    ERR_INVALID_MEASPARAM_AVG_RAM = -111
    ERR_INVALID_MEASPARAM_SYNC_RAM = -112
    ERR_INVALID_MEASPARAM_LEVEL_RAM = -113
    ERR_INVALID_MEASPARAM_SAT2_RAM = -114
    ERR_INVALID_MEASPARAM_FWVER_RAM = -115
    ERR_INVALID_MEASPARAM_DYNDARK = -116

    ERR_NOT_SUPPORTED_BY_SENSOR_TYPE = -120
    ERR_NOT_SUPPORTED_BY_FW_VER = -121
    ERR_NOT_SUPPORTED_BY_FPGA_VER = -122

    # 杂散光抑制
    ERR_SL_CALIBRATION_NOT_AVAILABLE = -140
    ERR_SL_STARTPIXEL_NOT_IN_RANGE = -141
    ERR_SL_ENDPIXEL_NOT_IN_RANGE = -142
    ERR_SL_STARTPIX_GT_ENDPIX = -143
    ERR_SL_MFACTOR_OUT_OF_RANGE = -144


class AvaError(RuntimeError):
    """avaspecx 所有异常的基类。"""

    func: str
    code: int


class AvsError(AvaError):
    """DLL 返回负错误码时抛出"""

    def __init__(self, func: str, code: int, message: str = ""):
        try:
            name = ErrCode(code).name
        except ValueError:
            name = "未知错误码"
        text = f"{func} 调用失败：{name}（{code}）"
        if message:
            text += f" -- {message}"
        super().__init__(text)
        self.func = func
        self.code = code


class UnsupportedPlatformError(AvaError):
    """当前平台没有注册 DLL 加载器"""


class DllNotFoundError(AvaError):
    """找不到可用的 DLL"""


class DllAlreadyLoadedError(AvaError):
    """本进程已加载另一份 DLL，拒绝再加载"""


class DeviceNotFoundError(AvaError):
    """`AVS_Init` 返回 0，或设备不可用/被其它程序占用"""


def check(res: int, func: str) -> int:
    """错误码拦截，`<0` 表示失败"""
    if res < 0:
        raise AvsError(func, res)
    return res
