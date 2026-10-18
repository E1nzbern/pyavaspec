"""features 与真实 ``Spectrometer`` 的结构兼容性（用快照替身，不需硬件）。

验证 ``DeviceAccess`` 协议确实被 ``Spectrometer`` 满足：features 的采集编排能直接接收
一台 ``Spectrometer``，而无需任何适配。
"""

from __future__ import annotations

import pytest

from _fakes import FakeDevice, FakeDriver
from pyavaspec.core import DriverSession, Spectrometer
from pyavaspec.features import capture_reference, check_reference, device_report


def make_spec(**device_kwargs: object) -> Spectrometer:
    device = FakeDevice(**device_kwargs)  # type: ignore[arg-type]
    session = DriverSession(driver=FakeDriver(device))  # type: ignore[attr-defined]
    session.open()
    return Spectrometer(session=session)


def test_features_accept_real_spectrometer() -> None:
    with make_spec(num_pixels=8) as spec:
        dark = capture_reference(spec, "dark")
        assert dark.serial == "FAKE0001"
        assert dark.spectrum.size == 8
        assert check_reference(dark, spec.measurement_config).ok is True

        report = device_report(spec)
        assert report.num_pixels == 8
        assert report.wavelength_range_nm == pytest.approx((400.0, 700.0))
        assert report.measurement_range_nm == pytest.approx((400.0, 700.0))
