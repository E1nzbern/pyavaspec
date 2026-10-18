"""core 用到的 ``LowLevelClient``接口"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from typing import Any, Protocol

import numpy as np

from .._lowlevel._structs import AvsIdentityType, DeviceConfigType, MeasConfigType
from .._lowlevel.client import RawScopeData, ScopeData, VersionInfo
from .errors import InvalidStateError, dll_errors

__all__ = ["BoundDevice", "DriverAdapter", "NativeClient"]

#: 空列表时重试枚举的次数和间隔，刚插拔设备或上一进程刚退出时 USB 可能还在重新枚举
_EMPTY_RETRIES = 3
_EMPTY_RETRY_S = 0.5


class NativeClient(Protocol):
    """原始低层 API :class:`~pyavaspec._lowlevel.client.AvaSpecx` 的内部接口

    供 :class:`DriverAdapter` 使用。
    """

    def open(self) -> Any: ...
    def close(self) -> None: ...
    def update_usb_devices(self) -> int: ...
    def get_list(self, count: int | None = None) -> list[AvsIdentityType]: ...
    def get_status_by_serial(self, serial: str) -> int: ...
    def activate(self, identity: AvsIdentityType) -> int: ...
    def deactivate(self, handle: int) -> None: ...
    def get_version_info(self, handle: int) -> VersionInfo: ...
    def get_num_pixels(self, handle: int) -> int: ...
    def get_lambda(self, handle: int, num_pixels: int = ...) -> np.ndarray: ...
    def get_detector_name(self, handle: int, selector: int) -> str: ...
    def get_parameter(self, handle: int) -> DeviceConfigType: ...
    def get_parameter_bytes(self, handle: int) -> bytes: ...
    def use_high_res_adc(self, handle: int, enable: bool = ...) -> None: ...
    def prepare_measure(self, handle: int, config: MeasConfigType) -> None: ...
    def measure(self, handle: int, nmsr: int = ..., hwnd: int | None = ...) -> None: ...
    def poll_scan(self, handle: int) -> bool: ...
    def stop_measure(self, handle: int) -> None: ...
    def get_scope_data(self, handle: int, num_pixels: int = ...) -> ScopeData: ...
    def get_raw_scope_data_crc(self, handle: int, num_pixels: int = ...) -> RawScopeData: ...
    def get_saturated_pixels(self, handle: int, num_pixels: int = ...) -> np.ndarray: ...
    def get_meas_pixels(self, handle: int) -> int: ...
    def set_prescan_mode(self, handle: int, enable: bool) -> None: ...
    def get_dig_in(self, handle: int, port: int) -> int: ...
    def set_dig_out(self, handle: int, port: int, value: int) -> None: ...
    def get_analog_in(self, handle: int, channel: int) -> float: ...
    def set_analog_out(self, handle: int, port: int, volts: float) -> None: ...
    def set_pwm_out(self, handle: int, port: int, frequency_hz: int, duty_cycle: int) -> None: ...
    def suppress_stray_light(
        self, handle: int, spectrum: Any, multi_factor: float = ...
    ) -> np.ndarray: ...


class DriverAdapter:
    """包装 :class:`NativeClient`，用于将返回码映射为具有实际含义的异常"""

    def __init__(self, client: NativeClient) -> None:
        self._client = client

    # %% _ports.SessionPort

    def open(self) -> None:
        self._client.open()

    def close(self) -> None:
        self._client.close()

    def list_devices(self) -> list[AvsIdentityType]:
        with dll_errors():
            # 正常路径只读一次 GetList，与原行为一致。
            # 只有列表为空时才尝试 AVS_UpdateUSBDevices：拔插 / 上一进程刚退出时
            # USB 列表可能过期，但频繁主动刷新会让设备重新枚举，反而增加风险。
            items = self._client.get_list()
            if items:
                return items
            for _ in range(_EMPTY_RETRIES):
                with contextlib.suppress(Exception):
                    self._client.update_usb_devices()
                time.sleep(_EMPTY_RETRY_S)
                items = self._client.get_list()
                if items:
                    return items
            return items

    def get_status(self, serial: str) -> int:
        with dll_errors():
            return self._client.get_status_by_serial(serial)

    def activate(self, identity: AvsIdentityType) -> int:
        with dll_errors():
            return int(self._client.activate(identity))

    def deactivate(self, handle: int) -> None:
        with dll_errors():
            self._client.deactivate(handle)

    def bind(self, handle: int, guard: Callable[[], None]) -> BoundDevice:
        """创建 :class:`BoundDevice`

        将句柄和存活判断函数封装在一起，得到一个与句柄类型无关的设备对象。
        """
        return BoundDevice(self, handle, guard)

    # %% _ports.DevicePrimitives

    def read_version(self, handle: int) -> VersionInfo:
        with dll_errors():
            return self._client.get_version_info(handle)

    def read_num_pixels(self, handle: int) -> int:
        with dll_errors():
            return int(self._client.get_num_pixels(handle))

    def read_parameter(self, handle: int) -> DeviceConfigType:
        with dll_errors():
            return self._client.get_parameter(handle)

    def read_parameter_bytes(self, handle: int) -> bytes:
        with dll_errors():
            return self._client.get_parameter_bytes(handle)

    def read_detector_name(self, handle: int, selector: int) -> str:
        with dll_errors():
            return self._client.get_detector_name(handle, selector)

    def read_lambda(self, handle: int, num_pixels: int) -> np.ndarray:
        with dll_errors():
            return self._client.get_lambda(handle, num_pixels)

    def set_high_res_adc(self, handle: int, enable: bool) -> None:
        with dll_errors():
            self._client.use_high_res_adc(handle, enable)

    def prepare(self, handle: int, config: MeasConfigType) -> None:
        with dll_errors():
            self._client.prepare_measure(handle, config)

    def set_prescan(self, handle: int, enable: bool) -> None:
        with dll_errors():
            self._client.set_prescan_mode(handle, enable)

    def read_meas_pixels(self, handle: int) -> int:
        with dll_errors():
            return int(self._client.get_meas_pixels(handle))

    def start(self, handle: int, nmsr: int) -> None:
        with dll_errors():
            self._client.measure(handle, nmsr)

    def poll_ready(self, handle: int) -> bool:
        with dll_errors():
            return bool(self._client.poll_scan(handle))

    def stop(self, handle: int) -> None:
        with dll_errors():
            self._client.stop_measure(handle)

    def read_frame(self, handle: int, num_pixels: int) -> ScopeData:
        with dll_errors():
            return self._client.get_scope_data(handle, num_pixels)

    def read_raw_frame(self, handle: int, num_pixels: int) -> RawScopeData:
        with dll_errors():
            return self._client.get_raw_scope_data_crc(handle, num_pixels)

    def read_saturated(self, handle: int, num_pixels: int) -> np.ndarray:
        with dll_errors():
            return self._client.get_saturated_pixels(handle, num_pixels)

    def read_dig_in(self, handle: int, port: int) -> int:
        with dll_errors():
            return int(self._client.get_dig_in(handle, port))

    def write_dig_out(self, handle: int, port: int, value: int) -> None:
        with dll_errors():
            self._client.set_dig_out(handle, port, value)

    def read_analog_in(self, handle: int, channel: int) -> float:
        with dll_errors():
            return float(self._client.get_analog_in(handle, channel))

    def write_analog_out(self, handle: int, port: int, volts: float) -> None:
        with dll_errors():
            self._client.set_analog_out(handle, port, volts)

    def write_pwm(self, handle: int, port: int, frequency_hz: int, duty_cycle: int) -> None:
        with dll_errors():
            self._client.set_pwm_out(handle, port, frequency_hz, duty_cycle)

    def suppress_stray_light(self, handle: int, spectrum: Any, multi_factor: float) -> np.ndarray:
        with dll_errors():
            return np.asarray(self._client.suppress_stray_light(handle, spectrum, multi_factor))


class BoundDevice:
    """已激活设备的句柄无关封装

    每次调用先检查有效性，再委托 DriverAdapter

    实现 :class:`DeviceReadPort`、:class:`ConfigPort`、:class:`AcquisitionPort`、
    :class:`IOPort`、:class:`ProcessingPort`
    """

    def __init__(
        self,
        driver: DriverAdapter,
        handle: int,
        guard: Callable[[], None],
    ) -> None:
        self._driver = driver
        self._handle = int(handle)
        self._guard = guard
        self._valid = True

    # %% 内部

    def _ensure(self) -> None:
        if not self._valid:
            raise InvalidStateError("设备句柄已失效；请重新打开设备")
        self._guard()

    def deactivate(self) -> None:
        """释放句柄"""
        if not self._valid:
            return
        self._valid = False
        with contextlib.suppress(Exception):
            self._driver.deactivate(self._handle)

    # %% _ports.DeviceReadPort

    def read_version(self) -> VersionInfo:
        self._ensure()
        return self._driver.read_version(self._handle)

    def read_num_pixels(self) -> int:
        self._ensure()
        return self._driver.read_num_pixels(self._handle)

    def read_parameter(self) -> DeviceConfigType:
        self._ensure()
        return self._driver.read_parameter(self._handle)

    def read_parameter_bytes(self) -> bytes:
        self._ensure()
        return self._driver.read_parameter_bytes(self._handle)

    def read_detector_name(self, selector: int) -> str:
        self._ensure()
        return self._driver.read_detector_name(self._handle, selector)

    def read_lambda(self, num_pixels: int) -> np.ndarray:
        self._ensure()
        return self._driver.read_lambda(self._handle, num_pixels)

    # %% _ports.ConfigPort

    def set_high_res_adc(self, enable: bool) -> None:
        self._ensure()
        self._driver.set_high_res_adc(self._handle, enable)

    def prepare(self, config: MeasConfigType) -> None:
        self._ensure()
        self._driver.prepare(self._handle, config)

    def set_prescan(self, enable: bool) -> None:
        self._ensure()
        self._driver.set_prescan(self._handle, enable)

    def read_meas_pixels(self) -> int:
        self._ensure()
        return self._driver.read_meas_pixels(self._handle)

    # %% _ports.AcquisitionPort

    def start(self, nmsr: int) -> None:
        self._ensure()
        self._driver.start(self._handle, nmsr)

    def poll_ready(self) -> bool:
        self._ensure()
        return self._driver.poll_ready(self._handle)

    def stop(self) -> None:
        self._ensure()
        self._driver.stop(self._handle)

    def read_frame(self, num_pixels: int) -> ScopeData:
        self._ensure()
        return self._driver.read_frame(self._handle, num_pixels)

    def read_raw_frame(self, num_pixels: int) -> RawScopeData:
        self._ensure()
        return self._driver.read_raw_frame(self._handle, num_pixels)

    def read_saturated(self, num_pixels: int) -> np.ndarray:
        self._ensure()
        return self._driver.read_saturated(self._handle, num_pixels)

    # %% _ports.IOPort

    def read_dig_in(self, port: int) -> int:
        self._ensure()
        return self._driver.read_dig_in(self._handle, port)

    def write_dig_out(self, port: int, value: int) -> None:
        self._ensure()
        self._driver.write_dig_out(self._handle, port, value)

    def read_analog_in(self, channel: int) -> float:
        self._ensure()
        return self._driver.read_analog_in(self._handle, channel)

    def write_analog_out(self, port: int, volts: float) -> None:
        self._ensure()
        self._driver.write_analog_out(self._handle, port, volts)

    def write_pwm(self, port: int, frequency_hz: int, duty_cycle: int) -> None:
        self._ensure()
        self._driver.write_pwm(self._handle, port, frequency_hz, duty_cycle)

    # %% _ports.ProcessingPort

    def suppress_stray_light(self, spectrum: np.ndarray, multi_factor: float) -> np.ndarray:
        self._ensure()
        return np.asarray(self._driver.suppress_stray_light(self._handle, spectrum, multi_factor))
