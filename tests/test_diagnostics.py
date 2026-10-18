"""features 设备诊断的脱机测试。"""

from __future__ import annotations

from dataclasses import replace

import pytest

from _fakes import FakeAccess, FakeIO
from pyavaspec.features import (
    device_report,
    digital_loopback,
    self_test,
)


class _BrokenIO:
    def digital_out(self, pin: int, value: bool) -> None:
        raise RuntimeError("no io")

    def digital_in(self, pin: int) -> bool:
        raise RuntimeError("no io")

    def board_temperature(self, channel: int = 0) -> float:
        raise RuntimeError("no temperature")


class _ReadBrokenIO:
    """``digital_out`` 可用、``digital_in`` 抛异常，用于验证引脚复位。"""

    def __init__(self) -> None:
        self.state: dict[int, bool] = {}

    def digital_out(self, pin: int, value: bool) -> None:
        self.state[int(pin)] = bool(value)

    def digital_in(self, pin: int) -> bool:
        raise RuntimeError("no input")

    def board_temperature(self, channel: int = 0) -> float:
        return 25.0


# %% device_report


def test_device_report_summarizes_device() -> None:
    report = device_report(FakeAccess())
    assert report.serial == "FAKE0001"
    assert report.num_pixels == 4
    assert report.detector_name == "FAKE"
    assert report.wavelength_range_nm == pytest.approx((400.0, 700.0))
    assert report.measurement_range_nm == pytest.approx((400.0, 700.0))
    assert report.has_spectrum_correction is True
    assert report.has_irradiance_calibration is False
    assert report.has_temperature_fit is True
    assert report.board_temperature_c == 25.0


class _SubRangeAccess(FakeAccess):
    """只测量中间两个像素的替身：全量波长不变，只改配置窗口。"""

    @property
    def measurement_config(self):
        return replace(super().measurement_config, start_pixel=1, stop_pixel=2)


def test_device_report_separates_full_and_measurement_range() -> None:
    report = device_report(_SubRangeAccess())
    assert report.wavelength_range_nm == pytest.approx((400.0, 700.0))
    assert report.measurement_range_nm == pytest.approx((500.0, 600.0))

    data = report.as_dict()
    assert data["wavelength_range_nm"] == pytest.approx([400.0, 700.0])
    assert data["measurement_range_nm"] == pytest.approx([500.0, 600.0])


def test_device_report_temperature_none_when_unreadable() -> None:
    report = device_report(FakeAccess(io=_BrokenIO()))
    assert report.board_temperature_c is None


class _NoTempFitAccess(FakeAccess):
    """EEPROM 里没有温度标定系数（全 0）：不应该报"有标定"。"""

    @property
    def config(self):
        return replace(super().config, temperature_fits=((0.0,) * 5,) * 3)


def test_device_report_without_temperature_fit() -> None:
    report = device_report(_NoTempFitAccess())
    assert report.has_temperature_fit is False


def test_device_report_as_dict() -> None:
    data = device_report(FakeAccess()).as_dict()
    assert data["wavelength_range_nm"] == pytest.approx([400.0, 700.0])
    assert data["measurement_range_nm"] == pytest.approx([400.0, 700.0])
    assert data["board_temperature_c"] == 25.0


# %% self_test


def test_self_test_passes_on_clean_device() -> None:
    report = self_test(FakeAccess(counts_per_ms=1.0))
    names = [check.name for check in report.checks]
    assert "board_temperature" in names
    assert "measure" in names
    assert report.ok is True


def test_self_test_flags_saturation() -> None:
    report = self_test(FakeAccess(counts_per_ms=1e9))
    measure = next(c for c in report.checks if c.name == "measure")
    assert measure.ok is False
    assert report.ok is False


def test_self_test_reports_unreadable_temperature_as_skipped() -> None:
    report = self_test(FakeAccess(io=_BrokenIO(), counts_per_ms=1.0))
    temperature = next(c for c in report.checks if c.name == "board_temperature")
    assert temperature.ok is None
    assert report.ok is True


def test_self_test_can_skip_measure() -> None:
    report = self_test(FakeAccess(), measure=False)
    assert [c.name for c in report.checks] == ["board_temperature"]


# %% digital_loopback


def test_digital_loopback_detected() -> None:
    result = digital_loopback(FakeAccess(io=FakeIO(loopback=True)))
    assert result.ok is True
    assert "已置低" in result.detail


def test_digital_loopback_absent_is_not_failure() -> None:
    result = digital_loopback(FakeAccess(io=FakeIO(loopback=False)))
    assert result.ok is None
    assert "已置低" in result.detail


def test_digital_loopback_io_error_is_failure() -> None:
    result = digital_loopback(FakeAccess(io=_BrokenIO()))
    assert result.ok is False


def test_digital_loopback_resets_output_when_read_fails() -> None:
    io = _ReadBrokenIO()
    result = digital_loopback(FakeAccess(io=io))
    assert result.ok is False
    assert io.state.get(5) is False
