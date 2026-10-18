"""core 数据模型与 ctypes 桥接的离线测试（不需要硬件）。"""

from __future__ import annotations

import numpy as np
import pytest

from pyavaspec._lowlevel._structs import AvsIdentityType, DeviceConfigType
from pyavaspec._lowlevel._types import DeviceStatus
from pyavaspec.core._bridge import (
    as_wavelength_slice,
    config_from_struct,
    identity_from_struct,
    meas_to_struct,
    status_from_code,
)
from pyavaspec.core.models import MeasurementConfig, Spectrum

# %% 身份 / 状态


def test_identity_from_struct_decodes_c_strings() -> None:
    struct = AvsIdentityType()
    struct.SerialNumber = b"1908062M1"
    struct.UserFriendlyName = b"my scope"
    struct.Status = 3

    identity = identity_from_struct(struct)
    assert identity.serial == "1908062M1"
    assert identity.name == "my scope"
    assert identity.status is DeviceStatus.USB_IN_USE_BY_OTHER
    assert identity.in_use is True


def test_status_from_code_unknown_falls_back() -> None:
    assert status_from_code(1) is DeviceStatus.USB_AVAILABLE
    assert status_from_code(123) is DeviceStatus.UNKNOWN


# %% 测量配置


def test_meas_to_struct_maps_nested_fields() -> None:
    cfg = MeasurementConfig(
        start_pixel=10,
        stop_pixel=20,
        integration_ms=12.5,
        integration_delay_ticks=7,
        averages=3,
        smoothing_pixels=2,
        smoothing_model=1,
        high_res_adc=False,
        saturation_detection=False,
        dynamic_dark=True,
        forget_percentage=50,
        store_to_ram=0,
        prescan=True,
    )
    struct = meas_to_struct(cfg)
    assert struct.m_StartPixel == 10
    assert struct.m_StopPixel == 20
    assert struct.m_IntegrationTime == pytest.approx(12.5)
    assert struct.m_IntegrationDelay == 7
    assert struct.m_NrAverages == 3
    assert struct.m_Smoothing.m_SmoothPix == 2
    assert struct.m_Smoothing.m_SmoothModel == 1
    assert struct.m_SaturationDetection == 0
    assert struct.m_CorDynDark.m_Enable == 1
    assert struct.m_CorDynDark.m_ForgetPercentage == 50


def test_meas_to_struct_clears_forget_when_dynamic_dark_off() -> None:
    cfg = MeasurementConfig(start_pixel=0, stop_pixel=3, integration_ms=5.0, dynamic_dark=False)
    struct = meas_to_struct(cfg)
    assert struct.m_CorDynDark.m_Enable == 0
    assert struct.m_CorDynDark.m_ForgetPercentage == 0


# %% 设备配置


def make_device_config_struct(num_pixels: int = 2048) -> DeviceConfigType:
    struct = DeviceConfigType()
    struct.m_Len = 63484
    struct.m_ConfigVersion = 257
    struct.m_aUserFriendlyId = b"scope"
    struct.m_Detector.m_NrPixels = num_pixels
    struct.m_Detector.m_SensorType = 22
    struct.m_Detector.m_aFit = (309.86, 0.303445, -8.5675e-06, -8.4766e-10, 0.0)
    struct.m_Detector.m_Gain = (1.0, 1.0)
    struct.m_Detector.m_Offset = (0.0, 0.0)
    struct.m_Detector.m_DefectivePixels[0] = 5
    struct.m_Detector.m_DefectivePixels[1] = 4095  # 空值，应被过滤
    struct.m_SpectrumCorrect.m_aSpectrumCorrect[0] = 1.5
    struct.m_Temperature[0].m_aFit = (1.0, 2.0, 0.0, 0.0, 0.0)
    struct.m_TecControl.m_Enable = True
    struct.m_TecControl.m_Setpoint = 5.0
    return struct


def test_config_from_struct_reads_nested_fields() -> None:
    struct = make_device_config_struct()
    cfg = config_from_struct(struct, b"raw-bytes")

    assert cfg.user_friendly_id == "scope"
    assert cfg.num_pixels == 2048
    assert cfg.sensor_type == 22
    assert cfg.wavelength_fit[0] == pytest.approx(309.86)
    assert cfg.defective_pixels == (5,)  # 4095 被过滤
    assert cfg.spectrum_correction_present is True
    assert cfg.irradiance_calibration_present is False
    assert cfg.temperature_fits[0][1] == pytest.approx(2.0)
    assert cfg.tec_enabled is True
    assert cfg.tec_setpoint == pytest.approx(5.0)
    assert cfg.config_len == 63484
    assert cfg.config_version == 257
    assert cfg.raw == b"raw-bytes"


def test_device_config_wavelength_horner() -> None:
    cfg = config_from_struct(make_device_config_struct())
    wl = cfg.wavelength(np.array([0.0, 1.0, 2.0]))
    assert wl[0] == pytest.approx(309.86, abs=1e-3)
    assert wl[1] == pytest.approx(309.86 + 0.303445 - 8.5675e-06 - 8.4766e-10, abs=1e-3)
    assert np.all(np.diff(wl) > 0)


# %% 波长切片


def test_as_wavelength_slice_matches_config() -> None:
    full = np.arange(10, dtype=np.float64)
    cfg = MeasurementConfig(start_pixel=2, stop_pixel=5, integration_ms=1.0)
    sliced = as_wavelength_slice(full, cfg)
    assert np.array_equal(sliced, [2.0, 3.0, 4.0, 5.0])
    assert sliced.size == cfg.num_pixels


# %% Spectrum


def make_spectrum() -> Spectrum:
    return Spectrum(
        wavelengths=np.array([400.0, 500.0, 600.0, 700.0]),
        counts=np.array([1.0, 9.0, 3.0, 2.0]),
        timestamp_ticks=123456,
        integration_ms=10.0,
        averages=1,
        start_pixel=0,
        stop_pixel=3,
        saturation_level=65535,
        sequence=1,
        host_time=1.0,
    )


def test_spectrum_stats_and_saturation() -> None:
    sp = make_spectrum()
    assert sp.size == 4
    assert sp.peak_index == 1
    assert sp.peak_wavelength_nm == pytest.approx(500.0)
    assert sp.peak_counts == pytest.approx(9.0)
    assert sp.max == pytest.approx(9.0)
    assert sp.min == pytest.approx(1.0)
    assert sp.mean == pytest.approx(3.75)
    assert sp.saturated is False
    assert sp.timestamp_s == pytest.approx(1.23456)


def test_spectrum_arrays_are_read_only() -> None:
    sp = make_spectrum()
    assert sp.counts.flags.writeable is False
    assert sp.wavelengths.flags.writeable is False
    with pytest.raises(ValueError):
        sp.counts[0] = 42.0


def test_spectrum_mismatched_lengths_raise() -> None:
    with pytest.raises(ValueError):
        Spectrum(
            wavelengths=np.zeros(3),
            counts=np.zeros(4),
            timestamp_ticks=0,
            integration_ms=1.0,
            averages=1,
            start_pixel=0,
            stop_pixel=3,
            saturation_level=65535,
        )


def test_spectrum_equals_uses_allclose() -> None:
    a = make_spectrum()
    b = make_spectrum()
    assert a.equals(b)
    assert not (a == b)  # noqa: SIM201  # eq=False：不应返回数组
    assert not a.equals("not a spectrum")


def test_spectrum_dict_roundtrip() -> None:
    sp = Spectrum(
        wavelengths=np.array([400.0, 500.0]),
        counts=np.array([1.0, 2.0]),
        timestamp_ticks=7,
        integration_ms=5.0,
        averages=2,
        start_pixel=3,
        stop_pixel=4,
        saturation_level=16383,
        saturated_mask=np.array([False, True]),
        raw_counts=np.array([10.0, 20.0]),
        raw_averages=2,
    )
    restored = Spectrum.from_dict(sp.to_dict())
    assert restored.equals(sp)
    assert np.array_equal(restored.saturated_mask, [False, True])
    assert np.array_equal(restored.raw_counts, [10.0, 20.0])
    assert restored.raw_averages == 2
    assert restored.saturation_level == 16383
