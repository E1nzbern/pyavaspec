"""core 杂散光抑制（DLL 原语经 capability port）的脱机测试。"""

from __future__ import annotations

import numpy as np
import pytest

from _fakes import FakeDevice, FakeDriver
from pyavaspec.core import (
    DeviceNotOpenError,
    DriverSession,
    InvalidParameterError,
    Spectrometer,
    Spectrum,
)


def make_spec(**device_kwargs: object) -> Spectrometer:
    device = FakeDevice(**device_kwargs)  # type: ignore[arg-type]
    session = DriverSession(driver=FakeDriver(device))  # type: ignore[attr-defined]
    session.open()
    return Spectrometer(session=session)


def _spectrum(num_pixels: int = 4) -> Spectrum:
    return Spectrum(
        wavelengths=np.linspace(400.0, 700.0, num_pixels),
        counts=np.full(num_pixels, 100.0),
        timestamp_ticks=1,
        integration_ms=5.0,
        averages=1,
        start_pixel=0,
        stop_pixel=num_pixels - 1,
        saturation_level=65535,
    )


def test_suppress_stray_light_returns_processed_spectrum() -> None:
    with make_spec() as spec:
        frame = spec.measure()
        processed = spec.suppress_stray_light(frame)

    assert isinstance(processed, Spectrum)
    assert processed.wavelengths is frame.wavelengths
    assert processed.integration_ms == frame.integration_ms
    assert processed.counts == pytest.approx(frame.counts * 0.5)
    assert frame.counts == pytest.approx(np.full(frame.size, frame.counts[0]))


def test_suppress_stray_light_passes_factor_and_counts() -> None:
    with make_spec(num_pixels=4) as spec:
        frame = spec.measure()
        source = frame.counts.copy()
        spec.suppress_stray_light(frame, multi_factor=1.5)
        device = spec._session.driver.device  # type: ignore[attr-defined]

    assert device.stray_light is not None
    factor, counts = device.stray_light
    assert factor == pytest.approx(1.5)
    assert counts == pytest.approx(source)


@pytest.mark.parametrize("factor", [-0.1, 2.1, -10.0])
def test_suppress_stray_light_rejects_out_of_range(factor: float) -> None:
    with make_spec() as spec:
        frame = spec.measure()
        with pytest.raises(InvalidParameterError):
            spec.suppress_stray_light(frame, multi_factor=factor)


def test_suppress_stray_light_rejects_non_spectrum() -> None:
    with make_spec() as spec, pytest.raises(TypeError):
        spec.suppress_stray_light(np.zeros(4))  # type: ignore[arg-type]


def test_suppress_stray_light_requires_open_device() -> None:
    spec = make_spec()
    with pytest.raises(DeviceNotOpenError):
        spec.suppress_stray_light(_spectrum())
