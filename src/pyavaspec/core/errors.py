"""异常和 DLL 返回码映射

底层 :mod:`pyavaspec._lowlevel._errors` 只提供 :class:`AvsError`，本模块将其翻译为有具体
含义的异常，并补齐 core 需要的类型。所有异常都继承自 :class:`AvaError`。
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from .._lowlevel._errors import (
    AvaError,
    AvsError,
    DeviceNotFoundError,
    DllAlreadyLoadedError,
    DllNotFoundError,
    ErrCode,
    UnsupportedPlatformError,
)

__all__ = [
    "AvaError",
    "AvsError",
    "CommunicationError",
    "DeviceBusyError",
    "DeviceNotFoundError",
    "DeviceNotOpenError",
    "DeviceWriteError",
    "DllAlreadyLoadedError",
    "DllNotFoundError",
    "ErrCode",
    "IncompleteAcquisitionError",
    "InvalidParameterError",
    "InvalidStateError",
    "MeasurementError",
    "MeasurementInProgressError",
    "MeasurementTimeoutError",
    "OperationNotSupportedError",
    "UnsupportedPlatformError",
    "dll_errors",
    "translate",
]


class DeviceBusyError(AvaError):
    """设备被其它进程或程序占用，例如 AvaSoft、AvaSoftX 等正在运行"""


class InvalidStateError(AvaError):
    """当前状态下不允许该操作，未打开、测量进行中、未配置等"""


class DeviceNotOpenError(InvalidStateError):
    """设备尚未打开就调用了需要打开状态的操作"""


class MeasurementInProgressError(InvalidStateError):
    """已有采集在进行：同实例重入，或采集期间修改配置"""


class InvalidParameterError(AvaError):
    """参数本地校验失败，或驱动以参数类错误码拒绝"""


class OperationNotSupportedError(AvaError):
    """当前设备、固件、传感器不支持该操作"""


class MeasurementError(AvaError):
    """采集失败，无数据、无缓冲区、板载 RAM 为空等"""


class MeasurementTimeoutError(MeasurementError):
    """等待测量完成超时"""


class IncompleteAcquisitionError(MeasurementError):
    """StoreToRam 取回的帧数少于请求值

    已成功取回的帧保留在 :attr:`partial_frames`
    """

    def __init__(
        self,
        message: str,
        frames: list | None = None,
        requested: int = 0,
    ) -> None:
        super().__init__(message)
        self.partial_frames: list = list(frames) if frames is not None else []
        self.requested: int = int(requested)


class CommunicationError(AvaError):
    """与设备的通信失败"""


class DeviceWriteError(AvaError):
    """写入设备参数后回读不一致，预留给 features 的 EEPROM 写入"""


# 返回码和异常的映射表，未命中的保留原始 ``AvsError``
_CODE_MAP: dict[ErrCode, type[AvaError]] = {
    ErrCode.ERR_INVALID_PARAMETER: InvalidParameterError,
    ErrCode.ERR_INVALID_PIXEL_RANGE: InvalidParameterError,
    ErrCode.ERR_INVALID_INT_TIME: InvalidParameterError,
    ErrCode.ERR_INVALID_COMBINATION: InvalidParameterError,
    ErrCode.ERR_INVALID_PARAMETER_NR_PIXEL: InvalidParameterError,
    ErrCode.ERR_INVALID_PARAMETER_ADC_GAIN: InvalidParameterError,
    ErrCode.ERR_INVALID_PARAMETER_ADC_OFFSET: InvalidParameterError,
    ErrCode.ERR_INVALID_MEASPARAM_AVG_SAT2: InvalidParameterError,
    ErrCode.ERR_INVALID_MEASPARAM_AVG_RAM: InvalidParameterError,
    ErrCode.ERR_INVALID_MEASPARAM_SYNC_RAM: InvalidParameterError,
    ErrCode.ERR_INVALID_MEASPARAM_LEVEL_RAM: InvalidParameterError,
    ErrCode.ERR_INVALID_MEASPARAM_SAT2_RAM: InvalidParameterError,
    ErrCode.ERR_INVALID_MEASPARAM_FWVER_RAM: InvalidParameterError,
    ErrCode.ERR_INVALID_MEASPARAM_DYNDARK: InvalidParameterError,
    ErrCode.ERR_DEVICE_NOT_FOUND: DeviceNotFoundError,
    ErrCode.ERR_OPERATION_NOT_SUPPORTED: OperationNotSupportedError,
    ErrCode.ERR_NOT_SUPPORTED_BY_SENSOR_TYPE: OperationNotSupportedError,
    ErrCode.ERR_NOT_SUPPORTED_BY_FW_VER: OperationNotSupportedError,
    ErrCode.ERR_NOT_SUPPORTED_BY_FPGA_VER: OperationNotSupportedError,
    ErrCode.ERR_INVALID_STATE: InvalidStateError,
    ErrCode.ERR_TIMEOUT: MeasurementTimeoutError,
    ErrCode.ERR_INVALID_MEAS_DATA: MeasurementError,
    ErrCode.ERR_NO_MEAS_BUFFER_AVAIL: MeasurementError,
    ErrCode.ERR_NO_SPECTRA_IN_RAM: MeasurementError,
    ErrCode.ERR_COMMUNICATION: CommunicationError,
    ErrCode.ERR_DLL_INITIALISATION: InvalidStateError,
}


def translate(exc: AvsError) -> AvaError:
    """把底层 :class:`AvsError` 映射为更有实际意义的异常，未知返回码则原样返回"""
    try:
        code: ErrCode | None = ErrCode(exc.code)
    except ValueError:
        code = None
    cls = _CODE_MAP.get(code) if code is not None else None
    if cls is None:
        return exc
    mapped = cls(str(exc))
    mapped.func = exc.func
    mapped.code = exc.code
    return mapped


@contextmanager
def dll_errors() -> Generator[None]:
    """把上下文内底层抛出的 :class:`AvsError` 翻译后再抛出"""
    try:
        yield
    except AvsError as exc:
        mapped = translate(exc)
        if mapped is exc:
            raise
        raise mapped from exc
