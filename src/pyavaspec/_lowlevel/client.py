"""`avaspecx64.dll` 的 Pythonic 包装。

- 句柄 `AvsHandle` 用 Python `int`；设备身份、配置等结构体在 `_structs.py`。
- 时间戳单位 10 µs ；积分时间单位 ms ；模拟输入单位 V。
- 返回码含义见 :class:`._errors.ErrCode`。
"""

from __future__ import annotations

import ctypes
import os
import threading
from typing import Any, NamedTuple, Self

import numpy as np

from . import _session
from ._binding import _AvaSpecxNative
from ._constants import DEVICE_CONFIG_LEN, MAX_PIXELS, VERSION_LEN
from ._errors import AvsError, check
from ._structs import AvsIdentityType, DeviceConfigType, MeasConfigType
from ._types import Port
from ._utils import _as_double_array, _as_u32_array, _cstr

__all__ = [
    "AvaSpecx",
    "AvsError",
    "RawScopeData",
    "ScopeData",
    "VersionInfo",
]


class VersionInfo(NamedTuple):
    """`AVS_GetVersionInfo` 的三个版本字符串，各 16 字节"""

    fpga: str
    firmware: str
    dll: str


class ScopeData(NamedTuple):
    """一帧光谱数据与硬件时间戳"""

    timestamp: int  # 设备上电起的 10 µs 计数
    spectrum: np.ndarray  # float64，长度由调用方指定，默认 MAX_PIXELS


class RawScopeData(NamedTuple):
    """未校正的原始像素值 `AVS_GetRawScopeDataCRC`"""

    timestamp: int
    averages: int
    crc32: int  # crc 需硬件支持
    num_pixels: int
    spectrum: np.ndarray  # float64，长度为 num_pixels


class AvaSpecx:
    """通过 AvaSpecx API 操作光谱仪

    支持上下文管理器，也可以把生命周期拆成 :meth:`open` / :meth:`close`。
    """

    def __init__(
        self,
        dll_path: str | os.PathLike[str] | None = None,
        *,
        port: int = Port.USB,
    ) -> None:
        self._dll_path = os.fspath(dll_path) if dll_path is not None else None
        self._port = int(port)
        self._lease: _session.Lease[_AvaSpecxNative] | None = None
        self.__raw: _AvaSpecxNative | None = None
        self._lock = threading.Lock()  # 只保护生命周期，不保护设备调用

    # %% 会话 / 生命周期

    @property
    def _raw(self) -> _AvaSpecxNative:
        if self.__raw is None:
            raise RuntimeError(
                "AvaSpecx 尚未打开：请使用 `with AvaSpecx() as ava:` 或先调用 ava.open()"
            )
        return self.__raw

    @property
    def path(self) -> str:
        """当前加载的 DLL 绝对路径"""
        return self._raw.path

    def open(self) -> Self:
        """开启会话，重复调用无副作用"""
        with self._lock:
            if self._lease is None:
                self._lease = _session.acquire(self._dll_path, self._port)
                self.__raw = self._lease.dll
        return self

    def close(self) -> None:
        """归还会话"""
        with self._lock:
            lease, self._lease = self._lease, None
            self.__raw = None
        if lease is not None:
            lease.close()

    def __enter__(self) -> Self:
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()

    def update_usb_devices(self) -> int:
        """刷新 USB 设备列表，返回设备数量"""
        return check(self._raw._UpdateUSBDevices(), "AVS_UpdateUSBDevices")

    # %% 枚举 / 激活

    def get_list(self, count: int | None = None) -> list[AvsIdentityType]:
        """
        枚举设备身份列表

        :param count: 指定设备数量，`None` 时返回全部设备
        """
        need = ctypes.c_uint32(0)
        size = max(1, int(count)) if count is not None else 1
        buf = (AvsIdentityType * size)()
        ret = self._raw._GetList(size * ctypes.sizeof(AvsIdentityType), ctypes.byref(need), buf)
        if ret < 0:
            raise AvsError("AVS_GetList", ret)
        total = need.value // ctypes.sizeof(AvsIdentityType)

        if count is None and total > size:
            size = total
            buf = (AvsIdentityType * size)()
            ret = self._raw._GetList(size * ctypes.sizeof(AvsIdentityType), ctypes.byref(need), buf)
            if ret < 0:
                raise AvsError("AVS_GetList", ret)
            total = need.value // ctypes.sizeof(AvsIdentityType)

        n = total if count is None else int(count)
        return [buf[i] for i in range(min(n, size))]

    def activate(self, identity: AvsIdentityType) -> int:
        """
        激活设备并返回句柄

        :return: 句柄，`<=0` 视为失败
        """
        handle = int(self._raw._Activate(ctypes.byref(identity)))
        if handle <= 0:
            raise AvsError("AVS_Activate", handle)
        return handle

    def deactivate(self, handle: int) -> None:
        """
        释放设备和句柄

        :param handle: 设备句柄
        """
        check(self._raw._Deactivate(int(handle)), "AVS_Deactivate")

    # %% 版本 / 设备信息

    def get_dll_version(self) -> str:
        """读取 DLL 版本信息，不需要先执行 :func:`init`"""
        buf = ctypes.create_string_buffer(64)
        check(self._raw._GetDLLVersion(buf), "AVS_GetDLLVersion")
        return _cstr(buf)

    def get_version_info(self, handle: int) -> VersionInfo:
        """读取 FPGA / 固件 / DLL 版本"""
        fpga = ctypes.create_string_buffer(VERSION_LEN)
        firmware = ctypes.create_string_buffer(VERSION_LEN)
        dll = ctypes.create_string_buffer(VERSION_LEN)
        check(
            self._raw._GetVersionInfo(int(handle), fpga, firmware, dll),
            "AVS_GetVersionInfo",
        )
        return VersionInfo(fpga=_cstr(fpga), firmware=_cstr(firmware), dll=_cstr(dll))

    def get_num_pixels(self, handle: int) -> int:
        """读取光谱仪的有效像素数"""
        n = ctypes.c_uint16()
        check(self._raw._GetNumPixels(int(handle), ctypes.byref(n)), "AVS_GetNumPixels")
        return int(n.value)

    def get_lambda(self, handle: int, num_pixels: int = MAX_PIXELS) -> np.ndarray:
        """读取像素和波长 (nm) 的映射"""
        buf = (ctypes.c_double * MAX_PIXELS)()
        check(self._raw._GetLambda(int(handle), buf), "AVS_GetLambda")
        return np.frombuffer(buf, dtype=np.float64, count=int(num_pixels)).copy()

    def get_detector_name(self, handle: int, selector: int) -> str:
        """
        探测器型号

        :param selector: 传感器类型选择，通常是配置里的 sensor_type
        """
        buf = ctypes.create_string_buffer(256)
        check(
            self._raw._GetDetectorName(int(handle), selector, buf),
            "AVS_GetDetectorName",
        )
        return _cstr(buf)

    def get_device_type(self, handle: int) -> int:
        """设备类型代号"""
        t = ctypes.c_int32()
        check(self._raw._GetDeviceType(int(handle), ctypes.byref(t)), "AVS_GetDeviceType")
        return int(t.value)

    def get_status_by_serial(self, serial: str) -> int:
        """按序列号查询设备状态代号，未知序列号返回 0(UNKNOWN)"""
        status = ctypes.c_ubyte()
        check(
            self._raw._GetStatusBySerial(
                serial.encode("ascii", errors="replace"), ctypes.byref(status)
            ),
            "AVS_GetStatusBySerial",
        )
        return int(status.value)

    def use_high_res_adc(self, handle: int, enable: bool = True) -> None:
        """切换 16bit / 14bit ADC"""
        check(self._raw._UseHighResAdc(int(handle), bool(enable)), "AVS_UseHighResAdc")

    # %% 配置读写

    def get_parameter(self, handle: int) -> DeviceConfigType:
        """读取完整设备配置"""
        cfg = DeviceConfigType()
        needed = ctypes.c_uint32(0)
        check(
            self._raw._GetParameter(
                int(handle), DEVICE_CONFIG_LEN, ctypes.byref(needed), ctypes.byref(cfg)
            ),
            "AVS_GetParameter",
        )
        return cfg

    def get_parameter_bytes(self, handle: int) -> bytes:
        """读取设备配置的原始字节，调试、备份用"""
        cfg = self.get_parameter(handle)
        return ctypes.string_at(ctypes.byref(cfg), DEVICE_CONFIG_LEN)

    # def set_parameter(self, handle: int, config: DeviceConfigType) -> None:
    #     """谨慎操作！写入完整设备配置，会写入设备 EEPROM
    #     """
    #     check(
    #         self._raw._SetParameter(int(handle), ctypes.byref(config)),
    #         "AVS_SetParameter",
    #     )

    # %% 采集

    def prepare_measure(self, handle: int, config: MeasConfigType) -> None:
        """下发测量配置，测量前必须先调用"""
        check(
            self._raw._PrepareMeasure(int(handle), ctypes.byref(config)),
            "AVS_PrepareMeasure",
        )

    def measure(self, handle: int, nmsr: int = 1, hwnd: int | None = None) -> None:
        """启动测量

        :param nmsr: 1=一帧、-1=连续、StoreToRam 用帧数配 1
        :param hwnd: Win32 窗口句柄，其余场景为 `None`
        """
        check(self._raw._Measure(int(handle), hwnd, int(nmsr)), "AVS_Measure")

    def poll_scan(self, handle: int) -> bool:
        """轮询测量是否就绪"""
        ret = int(self._raw._PollScan(int(handle)))
        if ret < 0:
            raise AvsError("AVS_PollScan", ret)
        return ret > 0

    def stop_measure(self, handle: int) -> None:
        """停止当前测量"""
        check(self._raw._StopMeasure(int(handle)), "AVS_StopMeasure")

    # def force_stop_meas(self, handle: int) -> None:
    #     """未验证方法！强制停止测量"""
    #     check(self._raw._ForceStopMeas(int(handle)), "AVS_ForceStopMeas")

    def get_scope_data(self, handle: int, num_pixels: int = MAX_PIXELS) -> ScopeData:
        """读取最近一帧的光谱和时间戳"""
        timestamp = ctypes.c_uint32()
        buf = (ctypes.c_double * MAX_PIXELS)()
        check(
            self._raw._GetScopeData(int(handle), ctypes.byref(timestamp), buf),
            "AVS_GetScopeData",
        )
        return ScopeData(
            timestamp=int(timestamp.value),
            spectrum=np.frombuffer(buf, dtype=np.float64, count=int(num_pixels)).copy(),
        )

    def get_raw_scope_data_crc(self, handle: int, num_pixels: int = MAX_PIXELS) -> RawScopeData:
        """读取未校正的原始像素值"""
        timestamp = ctypes.c_uint32()
        averages = ctypes.c_uint16()
        crc = ctypes.c_uint32()
        nr_pixels = ctypes.c_uint16()
        buf = (ctypes.c_uint32 * MAX_PIXELS)()
        check(
            self._raw._GetRawScopeDataCRC(
                int(handle),
                ctypes.byref(timestamp),
                ctypes.byref(averages),
                ctypes.byref(crc),
                ctypes.byref(nr_pixels),
                buf,
            ),
            "AVS_GetRawScopeDataCRC",
        )
        n = int(nr_pixels.value) or int(num_pixels)
        return RawScopeData(
            timestamp=int(timestamp.value),
            averages=int(averages.value),
            crc32=int(crc.value),
            num_pixels=n,
            spectrum=np.frombuffer(buf, dtype=np.uint32, count=min(n, MAX_PIXELS)).astype(
                np.float64
            ),
        )

    def get_saturated_pixels(self, handle: int, num_pixels: int = MAX_PIXELS) -> np.ndarray:
        """查询各像素的饱和状态"""
        buf = (ctypes.c_ubyte * MAX_PIXELS)()
        check(self._raw._GetSaturatedPixels(int(handle), buf), "AVS_GetSaturatedPixels")
        return np.frombuffer(buf, dtype=np.uint8, count=int(num_pixels)).astype(bool)

    def get_meas_pixels(self, handle: int) -> int:
        """本次实际测量的像素数量"""
        n = ctypes.c_uint32()
        check(self._raw._GetMeasPixels(int(handle), ctypes.byref(n)), "AVS_GetMeasPixels")
        return int(n.value)

    def check_crc(self, crc32: int, num_pixels: int, use_16bit: bool, spectrum: Any) -> bool:
        """校验一帧原始数据"""
        return bool(
            self._raw._CheckCRC(
                int(crc32),
                int(num_pixels),
                bool(use_16bit),
                _as_u32_array(spectrum),
            )
        )

    def enable_crc(self, handle: int, enable: bool = True) -> None:
        """启用 CRC 功能，需要硬件支持"""
        check(self._raw._EnableCRC(int(handle), bool(enable)), "AVS_EnableCRC")

    def set_prescan_mode(self, handle: int, enable: bool) -> None:
        """启动预扫描，即丢弃前若干次扫描"""
        check(self._raw._SetPrescanMode(int(handle), bool(enable)), "AVS_SetPrescanMode")

    def suppress_stray_light(
        self, handle: int, spectrum: Any, multi_factor: float = 0.5
    ) -> np.ndarray:
        """杂散光抑制

        :param multi_factor: 有效范围 0-2 ，越界返回 -144
        """
        src = _as_double_array(spectrum)
        dst = (ctypes.c_double * MAX_PIXELS)()
        check(
            self._raw._SuppressStrayLight(int(handle), multi_factor, src, dst),
            "AVS_SuppressStrayLight",
        )
        n = int(np.asarray(spectrum).size)
        return np.frombuffer(dst, dtype=np.float64, count=min(n, MAX_PIXELS)).copy()

    # %% IO

    def get_dig_in(self, handle: int, port: int) -> int:
        """读取数字输入"""
        value = ctypes.c_ubyte()
        check(
            self._raw._GetDigIn(int(handle), port, ctypes.byref(value)),
            "AVS_GetDigIn",
        )
        return int(value.value)

    def set_dig_out(self, handle: int, port: int, value: int) -> None:
        """设置数字输出"""
        check(
            self._raw._SetDigOut(int(handle), port, value),
            "AVS_SetDigOut",
        )

    def get_analog_in(self, handle: int, channel: int) -> float:
        """读模拟输入电压，单位 V ，通道 0 为板载温度传感器"""
        value = ctypes.c_float()
        check(
            self._raw._GetAnalogIn(int(handle), channel, ctypes.byref(value)),
            "AVS_GetAnalogIn",
        )
        return float(value.value)

    def set_analog_out(self, handle: int, port: int, volts: float) -> None:
        """设置模拟输出电压，单位 V"""
        check(
            self._raw._SetAnalogOut(int(handle), port, volts),
            "AVS_SetAnalogOut",
        )

    def set_pwm_out(self, handle: int, port: int, frequency_hz: int, duty_cycle: int) -> None:
        """PWM 输出，需要硬件支持"""
        check(
            self._raw._SetPwmOut(
                int(handle),
                port,
                frequency_hz,
                duty_cycle,
            ),
            "AVS_SetPwmOut",
        )

    # %% 同步 / 灵敏度 / 复位

    def set_sync_mode(self, handle: int, enable: int) -> None:
        """设置多机同步模式，需要硬件支持"""
        check(self._raw._SetSyncMode(int(handle), enable), "AVS_SetSyncMode")

    def set_sensitivity_mode(self, handle: int, mode: int) -> None:
        """设置灵敏度模式，需要硬件支持"""
        check(
            self._raw._SetSensitivityMode(int(handle), mode),
            "AVS_SetSensitivityMode",
        )

    def reset_device(self, handle: int) -> int:
        """软复位设备

        返回码为 `-16 ERR_COMMUNICATION` 时一般是设备正在重启，因此暂不作为错误抛出
        """
        ret = int(self._raw._ResetDevice(int(handle)))
        if ret < 0 and ret != -16:
            raise AvsError("AVS_ResetDevice", ret)
        return ret
