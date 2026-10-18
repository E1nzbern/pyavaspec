"""按 capability port 拆分的测试替身（不需要硬件）。

- :class:`FakeDevice`：一个已激活设备句柄上的四个窄 port 的组合，模拟
  :class:`~pyavaspec.core._driver.BoundDevice`（含存活守卫）。
- :class:`FakeDriver`：模拟 :class:`~pyavaspec.core._driver.DriverAdapter`
  （会话方法 + ``bind``），用于 ``DriverSession(driver=...)`` 注入。
- :class:`FakeNativeClient`：原始低层客户端替身，用于验证 ``DriverAdapter`` 的返回码翻译。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import numpy as np

from pyavaspec._lowlevel._errors import AvsError
from pyavaspec._lowlevel._structs import AvsIdentityType, DeviceConfigType
from pyavaspec._lowlevel._types import DeviceStatus
from pyavaspec._lowlevel.client import RawScopeData, ScopeData, VersionInfo
from pyavaspec.core.errors import InvalidStateError, MeasurementError
from pyavaspec.core.models import (
    DeviceConfig,
    DeviceInfo,
    MeasurementConfig,
    Spectrum,
    replace_present,
)

if TYPE_CHECKING:
    from pyavaspec.features._device import DeviceIOPort

__all__ = [
    "FakeAccess",
    "FakeDevice",
    "FakeDriver",
    "FakeIO",
    "FakeNativeClient",
    "FakeReadPort",
]


class FakeDevice:
    """四个窄 port 的组合替身；每个方法先过存活守卫，模拟 ``BoundDevice``。"""

    def __init__(
        self,
        *,
        num_pixels: int = 4,
        poll_results: list[bool] | None = None,
        scope_limit: int | None = None,
        reported_meas_pixels: int | None = None,
        fail_start: int | None = None,
    ) -> None:
        self._valid = True
        self._guard = lambda: None
        self.num_pixels = num_pixels
        self.reported_meas_pixels = reported_meas_pixels
        self.prepared: list[object] = []
        self.measure_calls: list[int] = []
        self.poll_calls = 0
        self.stop_calls = 0
        self.dig_out: tuple[int, int] | None = None
        self.analog_out: tuple[int, float] | None = None
        self.pwm: tuple[int, int, int] | None = None
        self.stray_light: tuple[float, np.ndarray] | None = None
        self.high_res: bool | None = None
        self.prescan: bool | None = None
        self.deactivated = False
        self._poll_results = list(poll_results) if poll_results is not None else None
        self._scope_limit = scope_limit
        self._scope_calls = 0
        self._fail_start = fail_start

    # %% 守卫（模拟 BoundDevice）

    def set_guard(self, guard) -> None:
        self._guard = guard

    def _ensure(self) -> None:
        if not self._valid:
            raise InvalidStateError("设备句柄已失效；请重新打开设备")
        self._guard()

    def deactivate(self) -> None:
        if not self._valid:
            return
        self._valid = False
        self.deactivated = True

    # %% DeviceReadPort

    def read_version(self) -> object:
        self._ensure()
        return SimpleNamespace(fpga="F", firmware="W", dll="D")

    def read_num_pixels(self) -> int:
        self._ensure()
        return self.num_pixels

    def read_parameter(self) -> DeviceConfigType:
        self._ensure()
        cfg = DeviceConfigType()
        cfg.m_Detector.m_NrPixels = self.num_pixels
        cfg.m_Detector.m_SensorType = 22
        # 与 read_lambda 的 linspace(400, 700) 一致，让全量波长范围与采集切片对得上
        step = 300.0 / (self.num_pixels - 1) if self.num_pixels > 1 else 0.0
        cfg.m_Detector.m_aFit = (400.0, step, 0.0, 0.0, 0.0)
        cfg.m_Temperature[0].m_aFit = (1.0, 0.0, 0.0, 0.0, 0.0)
        return cfg

    def read_parameter_bytes(self) -> bytes:
        self._ensure()
        return b"cfg"

    def read_detector_name(self, selector: int) -> str:
        self._ensure()
        return "FAKE"

    def read_lambda(self, num_pixels: int) -> np.ndarray:
        self._ensure()
        return np.linspace(400.0, 700.0, self.num_pixels)

    # %% ConfigPort

    def set_high_res_adc(self, enable: bool) -> None:
        self._ensure()
        self.high_res = enable

    def prepare(self, config: object) -> None:
        self._ensure()
        self.prepared.append(config)

    def set_prescan(self, enable: bool) -> None:
        self._ensure()
        self.prescan = enable

    def read_meas_pixels(self) -> int:
        self._ensure()
        if self.reported_meas_pixels is not None:
            return self.reported_meas_pixels
        return self.num_pixels

    # %% AcquisitionPort

    def start(self, nmsr: int) -> None:
        self._ensure()
        if self._fail_start is not None:
            raise AvsError("AVS_Measure", self._fail_start)
        self.measure_calls.append(nmsr)

    def poll_ready(self) -> bool:
        self._ensure()
        self.poll_calls += 1
        if self._poll_results is None:
            return True
        return bool(self._poll_results.pop(0)) if self._poll_results else False

    def stop(self) -> None:
        self._ensure()
        self.stop_calls += 1

    def read_frame(self, num_pixels: int) -> ScopeData:
        self._ensure()
        self._scope_calls += 1
        if self._scope_limit is not None and self._scope_calls > self._scope_limit:
            exc = MeasurementError("板载 RAM 中已无光谱")
            exc.code = -17  # ERR_NO_SPECTRA_IN_RAM（port 语义：已翻译）
            raise exc
        return ScopeData(
            timestamp=self._scope_calls,
            spectrum=np.full(num_pixels, 100.0 + self._scope_calls),
        )

    def read_raw_frame(self, num_pixels: int) -> RawScopeData:
        self._ensure()
        return RawScopeData(
            timestamp=0,
            averages=1,
            crc32=0,
            num_pixels=num_pixels,
            spectrum=np.full(num_pixels, 1.0),
        )

    def read_saturated(self, num_pixels: int) -> np.ndarray:
        self._ensure()
        mask = np.zeros(num_pixels, dtype=bool)
        mask[0] = True
        return mask

    # %% IOPort

    def read_dig_in(self, port: int) -> int:
        self._ensure()
        return 1

    def write_dig_out(self, port: int, value: int) -> None:
        self._ensure()
        self.dig_out = (port, value)

    def read_analog_in(self, channel: int) -> float:
        self._ensure()
        return 1.25

    def write_analog_out(self, port: int, volts: float) -> None:
        self._ensure()
        self.analog_out = (port, volts)

    def write_pwm(self, port: int, frequency_hz: int, duty_cycle: int) -> None:
        self._ensure()
        self.pwm = (port, frequency_hz, duty_cycle)

    # %% ProcessingPort

    def suppress_stray_light(self, spectrum: np.ndarray, multi_factor: float) -> np.ndarray:
        self._ensure()
        array = np.asarray(spectrum, dtype=np.float64)
        self.stray_light = (multi_factor, array.copy())
        return array * 0.5


class FakeReadPort:
    """只实现 :class:`~pyavaspec.core._ports.DeviceReadPort` 6 个方法的替身。

    供 ``core._snapshot`` 的脱机测试使用：不激活设备、不碰 ``Spectrometer`` 生命周期，
    并记录调用顺序以验证读取协议。
    """

    def __init__(
        self,
        *,
        num_pixels: int = 4,
        sensor_type: int = 22,
        detector_name: str = "FAKE",
        temperature_fit: tuple[float, ...] = (1.0, 0.0, 0.0, 0.0, 0.0),
        config_pixels: int | None = None,
    ) -> None:
        self.num_pixels = num_pixels
        self.sensor_type = sensor_type
        self.detector_name = detector_name
        self.temperature_fit = temperature_fit
        self.config_pixels = num_pixels if config_pixels is None else config_pixels
        self.calls: list[str] = []
        self.detector_name_selectors: list[int] = []

    def read_version(self) -> VersionInfo:
        self.calls.append("read_version")
        return VersionInfo(fpga="F", firmware="W", dll="D")

    def read_num_pixels(self) -> int:
        self.calls.append("read_num_pixels")
        return self.num_pixels

    def read_parameter(self) -> DeviceConfigType:
        self.calls.append("read_parameter")
        cfg = DeviceConfigType()
        cfg.m_Detector.m_NrPixels = self.config_pixels
        cfg.m_Detector.m_SensorType = self.sensor_type
        step = 300.0 / (self.num_pixels - 1) if self.num_pixels > 1 else 0.0
        cfg.m_Detector.m_aFit = (400.0, step, 0.0, 0.0, 0.0)
        cfg.m_Temperature[0].m_aFit = self.temperature_fit
        return cfg

    def read_parameter_bytes(self) -> bytes:
        self.calls.append("read_parameter_bytes")
        return b"cfg"

    def read_detector_name(self, selector: int) -> str:
        self.calls.append("read_detector_name")
        self.detector_name_selectors.append(selector)
        return self.detector_name

    def read_lambda(self, num_pixels: int) -> np.ndarray:
        self.calls.append("read_lambda")
        return np.linspace(400.0, 700.0, num_pixels)


class FakeDriver:
    """``DriverAdapter`` 的替身：会话方法 + ``bind`` 返回 :class:`FakeDevice`。"""

    def __init__(self, device: FakeDevice | None = None) -> None:
        self._device = device if device is not None else FakeDevice()
        self.opened = False
        self.closed = False
        self.activated = 0
        self.status_calls: list[str] = []

    @property
    def device(self) -> FakeDevice:
        return self._device

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.closed = True

    def list_devices(self) -> list[AvsIdentityType]:
        ident = AvsIdentityType()
        ident.SerialNumber = b"FAKE0001"
        ident.UserFriendlyName = b"fake"
        ident.Status = 1
        return [ident]

    def get_status(self, serial: str) -> int:
        self.status_calls.append(serial)
        return 1

    def activate(self, identity: object) -> int:
        self.activated += 1
        return 1

    def deactivate(self, handle: int) -> None:
        self._device.deactivate()

    def bind(self, handle: int, guard) -> FakeDevice:
        self._device.set_guard(guard)
        return self._device


class FakeNativeClient:
    """原始 ``NativeClient`` 替身：指定方法返回或抛 ``AvsError``，供翻译测试。"""

    def __init__(self, **results: object) -> None:
        self._results = results

    def _resolve(self, name: str) -> object:
        value = self._results.get(name, None)
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value()
        return value

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)

        def _call(*args: object, **kwargs: object) -> object:
            return self._resolve(name)

        return _call

    def open(self) -> None:
        return None

    def close(self) -> None:
        return None


class FakeIO:
    """``DeviceIO`` 的替身：数字输出带可选内部回环，板载温度可配。"""

    def __init__(self, *, temperature: float = 25.0, loopback: bool = True) -> None:
        self.temperature = temperature
        self.loopback = loopback
        self._out: dict[int, bool] = {}

    def digital_out(self, pin: int, value: bool) -> None:
        self._out[int(pin)] = bool(value)

    def digital_in(self, pin: int) -> bool:
        if self.loopback:
            return self._out.get(int(pin), False)
        return False

    def board_temperature(self, channel: int = 0) -> float:
        return self.temperature


class FakeAccess:
    """实现 ``features.DeviceAccess`` 的最小替身。

    ``measure`` 的峰值按 ``counts_per_ms * integration_ms`` 线性变化并截断到
    满量程，便于自动曝光测试收敛；平均次数只降噪、不改变峰值，因此不计入。
    """

    def __init__(
        self,
        *,
        num_pixels: int = 4,
        serial: str = "FAKE0001",
        integration_ms: float = 10.0,
        averages: int = 1,
        counts_per_ms: float = 10.0,
        io: DeviceIOPort | None = None,
    ) -> None:
        self._config = MeasurementConfig(
            start_pixel=0,
            stop_pixel=max(0, num_pixels - 1),
            integration_ms=integration_ms,
            averages=averages,
        )
        self._num_pixels = num_pixels
        self._counts_per_ms = counts_per_ms
        self._io = io if io is not None else FakeIO()
        wavelengths = np.linspace(400.0, 700.0, num_pixels)
        wavelengths.flags.writeable = False
        self._wavelengths = wavelengths
        step = 300.0 / (num_pixels - 1) if num_pixels > 1 else 0.0
        self._info = DeviceInfo(
            serial=serial,
            name="fake access",
            status=DeviceStatus.USB_AVAILABLE,
            num_pixels=num_pixels,
            sensor_type=22,
            detector_name="FAKE",
            fpga_version="F",
            firmware_version="W",
            dll_version="D",
        )
        self._device_config = DeviceConfig(
            user_friendly_id="fake",
            num_pixels=num_pixels,
            sensor_type=22,
            wavelength_fit=(400.0, step, 0.0, 0.0, 0.0),
            defective_pixels=(),
            nonlinearity_enabled=False,
            adc_gain=(1.0, 1.0),
            adc_offset=(0.0, 0.0),
            spectrum_correction_present=True,
            irradiance_calibration_present=False,
            reflectance_calibration_present=False,
            temperature_fits=((1.0, 0.0, 0.0, 0.0, 0.0),),
            tec_enabled=False,
            tec_setpoint=0.0,
            config_len=1,
            config_version=1,
        )
        self.measure_calls = 0

    @property
    def measurement_config(self) -> MeasurementConfig:
        return self._config

    @property
    def info(self) -> DeviceInfo:
        return self._info

    @property
    def config(self) -> DeviceConfig:
        return self._device_config

    @property
    def wavelengths(self) -> np.ndarray:
        return self._wavelengths

    @property
    def io(self) -> DeviceIOPort:
        return self._io

    def configure(
        self,
        *,
        integration_ms: float | None = None,
        averages: int | None = None,
    ) -> MeasurementConfig:
        self._config = replace_present(
            self._config,
            {"integration_ms": integration_ms, "averages": averages},
        )
        return self._config

    def measure(
        self,
        *,
        timeout_s: float | None = None,
        raw: bool = False,
        saturated_mask: bool = False,
    ) -> Spectrum:
        self.measure_calls += 1
        peak = self._counts_per_ms * self._config.integration_ms
        level = float(self._config.saturation_level)
        peak = min(peak, level)
        mask = np.full(self._num_pixels, peak >= level, dtype=bool) if saturated_mask else None
        return Spectrum(
            wavelengths=self._wavelengths,
            counts=np.full(self._num_pixels, peak, dtype=np.float64),
            timestamp_ticks=self.measure_calls,
            integration_ms=self._config.integration_ms,
            averages=self._config.averages,
            start_pixel=self._config.start_pixel,
            stop_pixel=self._config.stop_pixel,
            saturation_level=self._config.saturation_level,
            sequence=self.measure_calls,
            saturated_mask=mask,
        )
