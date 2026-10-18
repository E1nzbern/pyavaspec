"""不可变数据模型"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields, replace
from typing import Any, cast

import numpy as np

from .._lowlevel._types import (
    DeviceStatus,
    SensorType,
    SmoothingModel,
    TriggerMode,
    TriggerSource,
    TriggerSourceType,
    display_name,
    try_enum,
)

__all__ = [
    "DeviceConfig",
    "DeviceIdentity",
    "DeviceInfo",
    "MeasurementConfig",
    "Spectrum",
    "Trigger",
]

#: 设备时间戳一个 tick 为 10 µs，或者说 100 kHz
TIMESTAMP_TICK_S = 1e-5
#: ``timestamp_ticks`` 是 32 位无符号计数器，周期约 11.93 小时
TIMESTAMP_WRAP_TICKS = 1 << 32


@dataclass(frozen=True, slots=True)
class Trigger:
    """设备触发配置。默认全 0 = 软件触发。

    软件触发和硬件触发（外部、边沿）已在 AvaSpec-2048-USB2 上实测验证。
    同步、电平、单次扫描模式尚未在实机验证。
    """

    mode: TriggerMode | int = TriggerMode.SOFTWARE
    source: TriggerSource | int = TriggerSource.EXTERNAL
    source_type: TriggerSourceType | int = TriggerSourceType.EDGE

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", try_enum(TriggerMode, self.mode))
        object.__setattr__(self, "source", try_enum(TriggerSource, self.source))
        object.__setattr__(self, "source_type", try_enum(TriggerSourceType, self.source_type))

    @property
    def is_software(self) -> bool:
        """
        是否软件触发

        ``mode == 0``
        """
        return self.mode == TriggerMode.SOFTWARE


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    """
    设备标识符

    来自 ``AVS_GetList``，未激活
    """

    serial: str
    name: str
    status: DeviceStatus

    @property
    def in_use(self) -> bool:
        return self.status in (
            DeviceStatus.USB_IN_USE_BY_APPLICATION,
            DeviceStatus.USB_IN_USE_BY_OTHER,
            DeviceStatus.ETH_IN_USE_BY_APPLICATION,
            DeviceStatus.ETH_IN_USE_BY_OTHER,
        )


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """已激活设备的完整信息"""

    serial: str
    name: str
    status: DeviceStatus
    num_pixels: int
    sensor_type: SensorType | int
    detector_name: str
    fpga_version: str
    firmware_version: str
    dll_version: str

    @property
    def in_use(self) -> bool:
        return self.status in (
            DeviceStatus.USB_IN_USE_BY_APPLICATION,
            DeviceStatus.USB_IN_USE_BY_OTHER,
            DeviceStatus.ETH_IN_USE_BY_APPLICATION,
            DeviceStatus.ETH_IN_USE_BY_OTHER,
        )

    @property
    def sensor_name(self) -> str:
        return display_name(self.sensor_type)


@dataclass(frozen=True, slots=True)
class DeviceConfig:
    """``AVS_GetParameter`` 设备配置的只读数据类"""

    user_friendly_id: str
    num_pixels: int
    sensor_type: SensorType | int
    wavelength_fit: tuple[float, float, float, float, float]
    defective_pixels: tuple[int, ...]
    nonlinearity_enabled: bool
    adc_gain: tuple[float, float]
    adc_offset: tuple[float, float]
    spectrum_correction_present: bool
    irradiance_calibration_present: bool
    reflectance_calibration_present: bool
    temperature_fits: tuple[tuple[float, ...], ...]
    tec_enabled: bool
    tec_setpoint: float
    config_len: int
    config_version: int
    raw: bytes = field(default=b"", repr=False)

    def wavelength(self, pixels: Any) -> np.ndarray:
        """用设备保存的标定多项式计算像素和波长 `nm` 的映射关系"""
        a = self.wavelength_fit
        p = np.asarray(pixels, dtype=np.float64)
        # 秦九韶算法
        return a[0] + p * (a[1] + p * (a[2] + p * (a[3] + p * a[4])))


@dataclass(frozen=True, slots=True)
class MeasurementConfig:
    """测量配置的只读数据类"""

    start_pixel: int
    stop_pixel: int
    integration_ms: float
    integration_delay_ticks: int = 0
    averages: int = 1
    smoothing_pixels: int = 0
    smoothing_model: SmoothingModel | int = SmoothingModel.AVERAGE
    high_res_adc: bool = True
    saturation_detection: bool = True
    dynamic_dark: bool = False
    forget_percentage: int = 100
    store_to_ram: int = 0
    trigger: Trigger = field(default_factory=Trigger)
    prescan: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "start_pixel", int(self.start_pixel))
        object.__setattr__(self, "stop_pixel", int(self.stop_pixel))
        object.__setattr__(self, "integration_ms", float(self.integration_ms))
        object.__setattr__(self, "integration_delay_ticks", int(self.integration_delay_ticks))
        object.__setattr__(self, "averages", int(self.averages))
        object.__setattr__(self, "smoothing_pixels", int(self.smoothing_pixels))
        object.__setattr__(self, "smoothing_model", try_enum(SmoothingModel, self.smoothing_model))
        object.__setattr__(self, "high_res_adc", bool(self.high_res_adc))
        object.__setattr__(self, "saturation_detection", bool(self.saturation_detection))
        object.__setattr__(self, "dynamic_dark", bool(self.dynamic_dark))
        object.__setattr__(self, "forget_percentage", int(self.forget_percentage))
        object.__setattr__(self, "store_to_ram", int(self.store_to_ram))
        object.__setattr__(self, "prescan", bool(self.prescan))
        if not isinstance(self.trigger, Trigger):
            raise TypeError("trigger 必须是 core.models.Trigger")

    @property
    def num_pixels(self) -> int:
        """光谱数据的像素数"""
        return max(0, self.stop_pixel - self.start_pixel + 1)

    @property
    def saturation_level(self) -> int:
        """
        满量程数值，取决于选择的 ADC 位数

        16 bit 为 65535，14 bit 为 16383
        """
        return 65535 if self.high_res_adc else 16383


def replace_present(base: MeasurementConfig, changes: Mapping[str, object]) -> MeasurementConfig:
    """合并测量配置，用 ``changes`` 里非 ``None`` 的字段覆盖 ``base``"""
    valid = {f.name for f in fields(MeasurementConfig)}
    unknown = set(changes) - valid
    if unknown:
        raise TypeError(f"未知的测量配置字段：{sorted(unknown)}")
    present = {name: value for name, value in changes.items() if value is not None}
    return replace(base, **cast("Any", present))


@dataclass(frozen=True, slots=True, eq=False)
class Spectrum:
    """单帧光谱数据类

    使用 :func:`equals` 比较两帧光谱在误差范围内是否相等

    使用 ``==`` 则是判断二者是否是同一个对象引用
    """

    #: 波长，单位 nm
    wavelengths: np.ndarray
    #: 强度，单位 ADU
    counts: np.ndarray
    #: 设备的硬件时间戳，从上电起以 10 µs 递增
    timestamp_ticks: int
    #: 积分时间，单位 ms
    integration_ms: float
    #: 平均次数
    averages: int
    #: 数据开始像素
    start_pixel: int
    #: 数据停止像素
    stop_pixel: int
    #: 最大数值范围
    saturation_level: int
    sequence: int = 0
    #: 本机时间戳
    host_time: float = 0.0
    #: 各像素饱和标志
    saturated_mask: np.ndarray | None = None
    #: 原始强度，未经设备校正
    raw_counts: np.ndarray | None = None
    #: 原始平均次数
    raw_averages: int | None = None

    def __post_init__(self) -> None:
        if self.wavelengths.size != self.counts.size:
            raise ValueError(
                f"wavelengths 长度 {self.wavelengths.size} 与 counts 长度 {self.counts.size} 不一致"
            )
        for array in (
            self.wavelengths,
            self.counts,
            self.saturated_mask,
            self.raw_counts,
        ):
            if array is not None and array.flags.writeable:
                array.flags.writeable = False

    # %% 统计量

    @property
    def size(self) -> int:
        return int(self.counts.size)

    @property
    def peak_index(self) -> int:
        return int(np.argmax(self.counts)) if self.counts.size else 0

    @property
    def peak_wavelength_nm(self) -> float:
        if not self.counts.size:
            return float("nan")
        return float(self.wavelengths[self.peak_index])

    @property
    def peak_counts(self) -> float:
        if not self.counts.size:
            return 0.0
        return float(self.counts[self.peak_index])

    @property
    def max(self) -> float:
        return float(self.counts.max()) if self.counts.size else 0.0

    @property
    def min(self) -> float:
        return float(self.counts.min()) if self.counts.size else 0.0

    @property
    def mean(self) -> float:
        return float(self.counts.mean()) if self.counts.size else 0.0

    @property
    def saturated(self) -> bool:
        """是否存在像素饱和，手动判断"""
        return bool(self.counts.size) and bool(np.any(self.counts >= self.saturation_level))

    @property
    def any_pixel_saturated(self) -> bool:
        """是否存在像素饱和"""
        if self.saturated_mask is not None:
            return bool(self.saturated_mask.any())
        return self.saturated

    @property
    def timestamp_s(self) -> float:
        """设备时间戳换算成秒，相对设备上电时间"""
        return self.timestamp_ticks * TIMESTAMP_TICK_S

    # %% 比较

    def equals(
        self,
        other: object,
        *,
        rtol: float = 1e-5,
        atol: float = 1e-8,
    ) -> bool:
        """比较两帧光谱在误差范围内是否相等"""
        if not isinstance(other, Spectrum):
            return False
        return (
            self.timestamp_ticks == other.timestamp_ticks
            and self.start_pixel == other.start_pixel
            and self.stop_pixel == other.stop_pixel
            and np.allclose(self.wavelengths, other.wavelengths, rtol=rtol, atol=atol)
            and np.allclose(self.counts, other.counts, rtol=rtol, atol=atol)
        )

    # %% 序列化

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "format": "pyavaspec-spectrum/1",
            "timestamp_ticks": int(self.timestamp_ticks),
            "integration_ms": float(self.integration_ms),
            "averages": int(self.averages),
            "start_pixel": int(self.start_pixel),
            "stop_pixel": int(self.stop_pixel),
            "saturation_level": int(self.saturation_level),
            "sequence": int(self.sequence),
            "host_time": float(self.host_time),
            "wavelengths": [float(x) for x in self.wavelengths],
            "counts": [float(x) for x in self.counts],
        }
        if self.saturated_mask is not None:
            data["saturated_mask"] = [bool(x) for x in self.saturated_mask]
        if self.raw_counts is not None:
            data["raw_counts"] = [float(x) for x in self.raw_counts]
            data["raw_averages"] = self.raw_averages
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Spectrum:
        mask = data.get("saturated_mask")
        raw = data.get("raw_counts")
        return cls(
            wavelengths=np.asarray(data["wavelengths"], dtype=np.float64),
            counts=np.asarray(data["counts"], dtype=np.float64),
            timestamp_ticks=int(data.get("timestamp_ticks", 0)),
            integration_ms=float(data.get("integration_ms", 0.0)),
            averages=int(data.get("averages", 1)),
            start_pixel=int(data.get("start_pixel", 0)),
            stop_pixel=int(data.get("stop_pixel", len(data["counts"]) - 1)),
            saturation_level=int(data.get("saturation_level", 65535)),
            sequence=int(data.get("sequence", 0)),
            host_time=float(data.get("host_time", 0.0)),
            saturated_mask=(np.asarray(mask, dtype=bool) if mask is not None else None),
            raw_counts=(np.asarray(raw, dtype=np.float64) if raw is not None else None),
            raw_averages=data.get("raw_averages"),
        )
