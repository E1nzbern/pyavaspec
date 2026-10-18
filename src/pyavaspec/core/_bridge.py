"""ctypes 结构体和 core 数据模型的转换"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from .._lowlevel._structs import AvsIdentityType, DeviceConfigType, MeasConfigType
from .._lowlevel._types import DeviceStatus, SensorType, try_enum
from .._lowlevel._utils import _cstr
from .models import (
    DeviceConfig,
    DeviceIdentity,
    MeasurementConfig,
)

__all__ = [
    "config_from_struct",
    "identity_from_struct",
    "meas_to_struct",
    "status_from_code",
]

_NULL_DEFECTIVE_PIXELS = (0, 4095)


def status_from_code(code: int) -> DeviceStatus:
    """将状态码转成 :class:`DeviceStatus`，未知码返回 `DeviceStatus.UNKNOWN`。"""
    try:
        return DeviceStatus(int(code))
    except ValueError:
        return DeviceStatus.UNKNOWN


def identity_from_struct(struct: AvsIdentityType) -> DeviceIdentity:
    """将 :class:`AvsIdentityType` 转换为 :class:`DeviceIdentity`"""
    return DeviceIdentity(
        serial=_cstr(struct.SerialNumber),
        name=_cstr(struct.UserFriendlyName),
        status=status_from_code(struct.Status),
    )


def _has_nonzero(values: Iterable[float], limit: int) -> bool:
    for i, value in enumerate(values):
        if i >= limit:
            break
        if abs(float(value)) > 1e-12:
            return True
    return False


def config_from_struct(cfg: DeviceConfigType, raw: bytes = b"") -> DeviceConfig:
    """将 :class:`DeviceConfigType` 转换为 :class:`DeviceConfig`"""
    detector = cfg.m_Detector
    num_pixels = int(detector.m_NrPixels) or 0

    return DeviceConfig(
        user_friendly_id=_cstr(cfg.m_aUserFriendlyId),
        num_pixels=num_pixels,
        sensor_type=try_enum(SensorType, int(detector.m_SensorType)),
        wavelength_fit=tuple(float(x) for x in detector.m_aFit),  # type: ignore[arg-type]
        defective_pixels=tuple(
            int(x) for x in detector.m_DefectivePixels if int(x) not in _NULL_DEFECTIVE_PIXELS
        ),
        nonlinearity_enabled=bool(detector.m_NLEnable),
        adc_gain=(float(detector.m_Gain[0]), float(detector.m_Gain[1])),
        adc_offset=(float(detector.m_Offset[0]), float(detector.m_Offset[1])),
        spectrum_correction_present=_has_nonzero(
            cfg.m_SpectrumCorrect.m_aSpectrumCorrect, num_pixels
        ),
        irradiance_calibration_present=_has_nonzero(
            cfg.m_Irradiance.m_IntensityCalib.m_aCalibConvers,
            num_pixels,
        ),
        reflectance_calibration_present=_has_nonzero(cfg.m_Reflectance.m_aCalibConvers, num_pixels),
        temperature_fits=tuple(
            tuple(float(x) for x in cfg.m_Temperature[i].m_aFit) for i in range(3)
        ),
        tec_enabled=bool(cfg.m_TecControl.m_Enable),
        tec_setpoint=float(cfg.m_TecControl.m_Setpoint),
        config_len=int(cfg.m_Len),
        config_version=int(cfg.m_ConfigVersion),
        raw=raw,
    )


def meas_to_struct(cfg: MeasurementConfig) -> MeasConfigType:
    """将 :class:`MeasurementConfig` 转换为 :class:`MeasConfigType`"""
    struct = MeasConfigType()
    struct.m_StartPixel = int(cfg.start_pixel)
    struct.m_StopPixel = int(cfg.stop_pixel)
    struct.m_IntegrationTime = float(cfg.integration_ms)
    struct.m_IntegrationDelay = int(cfg.integration_delay_ticks)
    struct.m_NrAverages = int(cfg.averages)
    struct.m_CorDynDark.m_Enable = 1 if cfg.dynamic_dark else 0
    struct.m_CorDynDark.m_ForgetPercentage = int(cfg.forget_percentage) if cfg.dynamic_dark else 0
    struct.m_Smoothing.m_SmoothPix = int(cfg.smoothing_pixels)
    struct.m_Smoothing.m_SmoothModel = int(cfg.smoothing_model)
    struct.m_SaturationDetection = 1 if cfg.saturation_detection else 0
    struct.m_Trigger.m_Mode = int(cfg.trigger.mode)
    struct.m_Trigger.m_Source = int(cfg.trigger.source)
    struct.m_Trigger.m_SourceType = int(cfg.trigger.source_type)
    struct.m_Control.m_StrobeControl = 0
    struct.m_Control.m_LaserDelay = 0
    struct.m_Control.m_LaserWidth = 0
    struct.m_Control.m_LaserWaveLength = 0.0
    struct.m_Control.m_StoreToRam = int(cfg.store_to_ram)
    return struct


def as_wavelength_slice(full: np.ndarray, cfg: MeasurementConfig) -> np.ndarray:
    """按 :class:`MeasurementConfig` 的像素范围裁剪完整波长数组"""
    return full[cfg.start_pixel : cfg.stop_pixel + 1]
