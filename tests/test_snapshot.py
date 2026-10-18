"""设备读取协议（``core._snapshot``）的脱机测试。

只用一个实现 ``DeviceReadPort`` 6 个方法的替身，不激活设备、不碰 ``Spectrometer``
生命周期——这正是 C8 把读取协议从 ``open()`` 里抽出来换到的可测性。
"""

from __future__ import annotations

import numpy as np
import pytest

from _fakes import FakeReadPort
from pyavaspec._lowlevel._types import DeviceStatus
from pyavaspec.core._snapshot import read_config, read_device
from pyavaspec.core.models import DeviceIdentity

_IDENTITY = DeviceIdentity(serial="FAKE0001", name="fake scope", status=DeviceStatus.USB_AVAILABLE)


def test_read_device_builds_info_config_and_wavelengths() -> None:
    reads = FakeReadPort(num_pixels=4, sensor_type=22, detector_name="FAKE")
    snapshot = read_device(reads, _IDENTITY)

    assert snapshot.info.serial == "FAKE0001"
    assert snapshot.info.name == "fake scope"
    assert snapshot.info.status is DeviceStatus.USB_AVAILABLE
    assert snapshot.info.num_pixels == 4
    assert snapshot.info.sensor_type == 22
    assert snapshot.info.detector_name == "FAKE"
    assert snapshot.info.fpga_version == "F"
    assert snapshot.info.firmware_version == "W"
    assert snapshot.info.dll_version == "D"

    assert snapshot.config.num_pixels == 4
    assert snapshot.config.raw == b"cfg"
    assert snapshot.wavelengths == pytest.approx(np.linspace(400.0, 700.0, 4))
    assert snapshot.temperature_fit == (1.0, 0.0, 0.0, 0.0, 0.0)


def test_temperature_fit_is_none_without_calibration() -> None:
    """全 0 系数 = 未标定：代入多项式只会得到 0 ℃ 这种假温度"""
    reads = FakeReadPort(temperature_fit=(0.0, 0.0, 0.0, 0.0, 0.0))
    snapshot = read_device(reads, _IDENTITY)
    assert snapshot.temperature_fit is None


def test_read_device_wavelengths_are_readonly() -> None:
    snapshot = read_device(FakeReadPort(), _IDENTITY)
    assert snapshot.wavelengths.flags.writeable is False


def test_read_device_uses_sensor_type_as_detector_selector() -> None:
    reads = FakeReadPort(sensor_type=17)
    read_device(reads, _IDENTITY)
    assert reads.detector_name_selectors == [17]


def test_read_device_reads_parameter_before_detector_name() -> None:
    reads = FakeReadPort()
    read_device(reads, _IDENTITY)
    assert reads.calls.index("read_parameter") < reads.calls.index("read_detector_name")
    assert reads.calls.index("read_num_pixels") < reads.calls.index("read_lambda")


def test_read_config_reads_bytes_then_parameter() -> None:
    reads = FakeReadPort()
    cfg = read_config(reads)
    assert reads.calls == ["read_parameter_bytes", "read_parameter"]
    assert cfg.raw == b"cfg"


def test_read_device_config_matches_standalone_read_config() -> None:
    snapshot = read_device(FakeReadPort(), _IDENTITY)
    assert snapshot.config == read_config(FakeReadPort())
