"""采集编排测试：按 capability port 注入测试替身（不需要硬件）。"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from _fakes import FakeDevice, FakeDriver
from pyavaspec.core import (
    AvsError,
    DeviceNotOpenError,
    DeviceWriteError,
    DriverSession,
    IncompleteAcquisitionError,
    InvalidParameterError,
    InvalidStateError,
    MeasurementConfig,
    MeasurementInProgressError,
    MeasurementTimeoutError,
    Port,
    Spectrometer,
    Trigger,
    TriggerMode,
)
from pyavaspec.core._acquisition import (
    DeviceLease,
    MeasurementRun,
    estimate_timeout,
    grab_frame,
    wait_ready,
)
from pyavaspec.core.device import _OPEN_DEVICES


def make_spec(**device_kwargs: object) -> Spectrometer:
    device = FakeDevice(**device_kwargs)  # type: ignore[arg-type]
    session = DriverSession(driver=FakeDriver(device))  # type: ignore[arg-type]
    session.open()
    return Spectrometer(session=session)


def _device(spec: Spectrometer) -> FakeDevice:
    return spec._session.driver.device  # type: ignore[attr-defined]


# %% 打开 / 信息


def test_open_sets_default_config_and_info() -> None:
    spec = make_spec()
    spec.open()
    try:
        assert spec.is_open is True
        assert spec.info.serial == "FAKE0001"
        assert spec.info.num_pixels == 4
        assert spec.num_pixels == 4
        cfg = spec.measurement_config
        assert (cfg.start_pixel, cfg.stop_pixel) == (0, 3)
        assert cfg.integration_ms == pytest.approx(10.0)
        assert spec.wavelengths.flags.writeable is False
    finally:
        spec.close()
    assert spec.is_open is False


def test_context_manager() -> None:
    with make_spec() as spec:
        assert spec.is_open is True
        assert spec in _OPEN_DEVICES
    assert spec.is_open is False
    assert spec not in _OPEN_DEVICES


# %% 单帧


def test_measure_returns_spectrum_and_increments_sequence() -> None:
    with make_spec() as spec:
        first = spec.measure()
        second = spec.measure()
    assert first.size == 4
    assert first.sequence == 1
    assert second.sequence == 2
    assert first.wavelengths is second.wavelengths  # 共享同一只读切片
    assert not first.wavelengths.flags.writeable


def test_measure_with_mask_and_raw() -> None:
    with make_spec() as spec:
        frame = spec.measure(raw=True, saturated_mask=True)
    assert frame.saturated_mask is not None
    assert frame.saturated_mask[0] is np.True_
    assert frame.raw_counts is not None
    assert frame.raw_averages == 1


def test_measure_timeout_stops_device() -> None:
    with make_spec(poll_results=[]) as spec:
        with pytest.raises(MeasurementTimeoutError):
            spec.measure(timeout_s=0.01)
        assert _device(spec).stop_calls >= 1


def test_estimate_timeout_covers_seconds_scale_integration() -> None:
    cfg = MeasurementConfig(start_pixel=0, stop_pixel=3, integration_ms=10_000.0)
    # 10 s 积分至少给出 2 倍积分时间的等待上限，避免在边界处误报超时
    assert estimate_timeout(cfg) >= 20.0
    assert estimate_timeout(cfg, 3) > estimate_timeout(cfg, 1)
    with pytest.raises(InvalidParameterError):
        estimate_timeout(cfg, explicit=0.0)


@pytest.mark.parametrize("mode", [TriggerMode.HARDWARE, TriggerMode.SINGLE_SCAN])
def test_estimate_timeout_requires_explicit_for_hardware_trigger(mode: TriggerMode) -> None:
    cfg = MeasurementConfig(
        start_pixel=0,
        stop_pixel=3,
        integration_ms=10.0,
        trigger=Trigger(mode=mode),
    )
    with pytest.raises(InvalidParameterError):
        estimate_timeout(cfg)
    assert estimate_timeout(cfg, explicit=3.0) == 3.0


def test_wait_ready_polls_with_backoff() -> None:
    device = FakeDevice(poll_results=[])
    with pytest.raises(MeasurementTimeoutError):
        wait_ready(device, 0.3)  # type: ignore[arg-type]
    # 2 ms 死循环会产生上百次 USB 查询；退避后应只有个位数到十几次
    assert device.poll_calls < 30
    assert device.stop_calls == 1


def test_measure_rejects_store_to_ram_config() -> None:
    with make_spec() as spec:
        spec.configure(store_to_ram=2)
        with pytest.raises(InvalidParameterError):
            spec.measure()


# %% 配置


def test_configure_validates_locally() -> None:
    with make_spec() as spec:
        with pytest.raises(InvalidParameterError):
            spec.configure(pixels=(0, 99))
        with pytest.raises(InvalidParameterError):
            spec.configure(integration_ms=0.0)
        with pytest.raises(InvalidParameterError):
            spec.configure(store_to_ram=5, averages=2)


def test_configure_during_measurement_raises() -> None:
    with make_spec() as spec:
        spec._lease.begin()  # type: ignore[attr-defined]
        try:
            with pytest.raises(MeasurementInProgressError):
                spec.configure(integration_ms=5.0)
        finally:
            spec._lease.end()  # type: ignore[attr-defined]


def test_not_open_raises_device_not_open() -> None:
    spec = make_spec()
    with pytest.raises(DeviceNotOpenError):
        spec.measure()
    with pytest.raises(DeviceNotOpenError):
        _ = spec.info
    assert issubclass(DeviceNotOpenError, InvalidStateError)


def test_apply_config_replaces_whole_config() -> None:
    with make_spec() as spec:
        target = replace(spec.measurement_config, integration_ms=42.0, averages=3)
        assert spec.apply_config(target) == target
        assert spec.measurement_config == target
        with pytest.raises(TypeError):
            spec.apply_config("not a config")  # type: ignore[arg-type]


# %% 连续采集上下文管理器


def test_stream_context_manager_stops_and_releases() -> None:
    with make_spec() as spec:
        with spec.stream() as stream:
            frames = [next(stream) for _ in range(3)]
        assert [f.sequence for f in frames] == [1, 2, 3]
        assert _device(spec).stop_calls >= 1
        assert spec.is_measuring() is False
        assert spec.measure().sequence == 4  # 锁已释放，可继续采集


def test_stream_break_inside_with_stops() -> None:
    with make_spec() as spec:
        with spec.stream() as stream:
            for _ in stream:
                break
        assert spec.is_measuring() is False


def test_stream_running_blocks_configure() -> None:
    with make_spec() as spec, spec.stream() as stream:
        next(stream)
        with pytest.raises(MeasurementInProgressError):
            spec.configure(integration_ms=5.0)


def test_configure_atomic_on_failure() -> None:
    with make_spec() as spec:
        original = spec.measurement_config
        with pytest.raises(InvalidParameterError):
            spec.configure(integration_ms=999_999_999.0)
        assert spec.measurement_config == original


def test_configure_verifies_readback_and_rolls_back() -> None:
    with make_spec() as spec:
        original = spec.measurement_config
        # FakeDevice 固定报告 4 个测量像素，裁剪到 2 个会回读不一致
        with pytest.raises(DeviceWriteError):
            spec.configure(pixels=(0, 1))
        assert spec.measurement_config == original
        # 失败后把旧配置（全范围）重新下发给硬件
        last = _device(spec).prepared[-1]
        assert (last.m_StartPixel, last.m_StopPixel) == (0, 3)


def test_configure_accepts_matching_readback() -> None:
    with make_spec() as spec:
        cfg = spec.configure(integration_ms=42.0)
        assert spec.measurement_config == cfg


# %% StoreToRam


def test_acquire_to_ram_returns_frames_and_resets() -> None:
    with make_spec() as spec:
        frames = spec.acquire_to_ram(3)
        assert [f.sequence for f in frames] == [1, 2, 3]
        assert spec.measurement_config.store_to_ram == 0
        last = _device(spec).prepared[-1]
        assert last.m_Control.m_StoreToRam == 0


def test_acquire_to_ram_resets_on_timeout() -> None:
    with make_spec(poll_results=[]) as spec:
        with pytest.raises(MeasurementTimeoutError):
            spec.acquire_to_ram(3, timeout_s=0.01)
        assert spec.measurement_config.store_to_ram == 0
        last = _device(spec).prepared[-1]
        assert last.m_Control.m_StoreToRam == 0


def test_incomplete_acquisition_keeps_partial_frames() -> None:
    with make_spec(scope_limit=2) as spec:
        with pytest.raises(IncompleteAcquisitionError) as excinfo:
            spec.acquire_to_ram(3)
        assert len(excinfo.value.partial_frames) == 2
        assert excinfo.value.requested == 3
        assert spec.measurement_config.store_to_ram == 0


# %% 采集运行时（DeviceLease / MeasurementRun）


def test_lease_begin_is_exclusive_and_releases() -> None:
    lease = DeviceLease()
    lease.begin()
    assert lease.measuring is True
    with pytest.raises(MeasurementInProgressError):
        lease.begin()
    lease.end()
    assert lease.measuring is False
    lease.begin()  # 释放后可再占用
    lease.end()


def test_lease_requires_attached_device() -> None:
    lease = DeviceLease()
    with pytest.raises(InvalidStateError):
        lease.acquisition()
    device = FakeDevice()
    lease.attach(device)
    assert lease.is_valid is True
    assert lease.acquisition() is device
    lease.release()
    assert lease.is_valid is False
    assert device.deactivated is True
    with pytest.raises(InvalidStateError):
        lease.acquisition()


def test_lease_sequence_is_monotonic() -> None:
    lease = DeviceLease()
    assert [lease.next_sequence() for _ in range(3)] == [1, 2, 3]


def test_run_releases_lease_when_start_fails() -> None:
    lease = DeviceLease()
    lease.attach(FakeDevice(fail_start=-9999))
    cfg = MeasurementConfig(start_pixel=0, stop_pixel=3, integration_ms=10.0)
    with pytest.raises(AvsError), MeasurementRun(lease, cfg, np.zeros(4), timeout_s=1.0):
        pass
    # 启动失败也得归还测量锁
    assert lease.measuring is False
    lease.begin()
    lease.end()


def test_grab_frame_builds_spectrum_from_port() -> None:
    device = FakeDevice(num_pixels=3)
    cfg = MeasurementConfig(start_pixel=0, stop_pixel=2, integration_ms=2.0)
    frame = grab_frame(
        device,
        cfg,
        np.array([400.0, 500.0, 600.0]),
        sequence=7,
        raw=True,
        saturated_mask=True,
    )
    assert frame.sequence == 7
    assert frame.size == 3
    assert frame.integration_ms == pytest.approx(2.0)
    assert frame.raw_averages == 1
    assert frame.saturated_mask is not None


# %% IO


def test_io_helpers() -> None:
    with make_spec() as spec:
        assert spec.io.digital_in(0) is True
        spec.io.digital_out(2, True)
        assert _device(spec).dig_out == (2, 1)
        assert spec.io.analog_in(0) == pytest.approx(1.25)
        spec.io.analog_out(0, 3.3)
        assert _device(spec).analog_out == (0, 3.3)
        with pytest.raises(InvalidParameterError):
            spec.io.digital_in(9)
        with pytest.raises(InvalidParameterError):
            spec.io.analog_in(99)


# %% 会话归属（C3）


def test_session_conflicts_with_dll_path_and_port() -> None:
    session = DriverSession(driver=FakeDriver())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Spectrometer(session=session, dll_path="C:/x/avaspecx64.dll")
    with pytest.raises(ValueError):
        Spectrometer(session=session, port=Port.USB)


def test_private_vs_borrowed_ownership_flag() -> None:
    session = DriverSession(driver=FakeDriver())  # type: ignore[arg-type]
    assert Spectrometer(session=session)._owns_session is False
    assert Spectrometer()._owns_session is True


def test_borrowed_session_must_be_open() -> None:
    session = DriverSession(driver=FakeDriver())  # type: ignore[arg-type]  # 故意不 open
    spec = Spectrometer(session=session)
    with pytest.raises(InvalidStateError):
        spec.open()
    assert spec.is_open is False


def test_spectrometer_does_not_close_borrowed_session() -> None:
    session = DriverSession(driver=FakeDriver())  # type: ignore[arg-type]
    with session:
        with Spectrometer(session=session) as spec:
            assert spec.is_open is True
        assert session.is_open is True  # 借用方不得关闭
    assert session.is_open is False


def test_closing_session_invalidates_device() -> None:
    session = DriverSession(driver=FakeDriver())  # type: ignore[arg-type]
    session.open()
    spec = Spectrometer(session=session)
    spec.open()
    session.close()
    with pytest.raises(InvalidStateError):
        spec.measure(timeout_s=0.1)
    with pytest.raises(InvalidStateError):
        spec.io.digital_in(0)
    spec.close()  # 幂等：不得因会话已关而抛异常
