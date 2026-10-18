"""设备租约和单次测量的运行时序"""

from __future__ import annotations

import contextlib
import threading
import time
from typing import Self

import numpy as np

from .._lowlevel._errors import ErrCode
from ._driver import BoundDevice
from ._ports import (
    AcquisitionPort,
    ConfigPort,
    DeviceReadPort,
    IOPort,
    ProcessingPort,
)
from .errors import (
    AvaError,
    IncompleteAcquisitionError,
    InvalidParameterError,
    InvalidStateError,
    MeasurementError,
    MeasurementInProgressError,
    MeasurementTimeoutError,
)
from .models import MeasurementConfig, Spectrum

__all__ = [
    "DeviceLease",
    "MeasurementRun",
    "estimate_timeout",
    "grab_frame",
    "wait_ready",
]

_POLL_INITIAL_S = 0.002  # 首次轮询间隔
_POLL_MAX_S = 0.05  # 轮询间隔上限，长积分时不要高频打扰设备
_POLL_BACKOFF = 2.0  # 轮询退避系数
_MIN_TIMEOUT_S = 2.0  # 最小等待超时
_SAFETY_FACTOR = 2.0  # 实际采集耗时相对 积分时间 * 平均 的预计最大值
_MARGIN_S = 5.0  # 估算超时的固定余量


class DeviceLease:
    """已打开设备的内部租约"""

    def __init__(self) -> None:
        self._device: BoundDevice | None = None
        self._measuring = False
        self._lock = threading.Lock()
        self._sequence = 0

    @property
    def is_valid(self) -> bool:
        return self._device is not None

    @property
    def measuring(self) -> bool:
        return self._measuring

    def attach(self, device: BoundDevice) -> None:
        """绑定已打开的 :class:`BoundDevice`"""
        self._device = device

    def release(self) -> None:
        """停止测量并释放设备，屏蔽所有异常，操作失效句柄会导致进程崩溃"""
        device, self._device = self._device, None
        self._measuring = False
        if device is None:
            return
        with contextlib.suppress(Exception):
            device.stop()
        with contextlib.suppress(Exception):
            device.deactivate()

    def _require_device(self) -> BoundDevice:
        device = self._device
        if device is None:
            raise InvalidStateError("设备句柄已失效；请重新打开设备")
        return device

    # %% 向外暴露设备的接口

    def acquisition(self) -> AcquisitionPort:
        return self._require_device()

    def config(self) -> ConfigPort:
        return self._require_device()

    def io(self) -> IOPort:
        return self._require_device()

    def processing(self) -> ProcessingPort:
        return self._require_device()

    def reads(self) -> DeviceReadPort:
        return self._require_device()

    # %% 测量

    def begin(self) -> None:
        """测量互斥锁，已被占用时抛 :class:`MeasurementInProgressError`"""
        if not self._lock.acquire(blocking=False):
            raise MeasurementInProgressError("该实例上已有采集在进行，同一实例只允许单线程调用")
        self._measuring = True

    def end(self) -> None:
        """释放测量互斥锁"""
        self._measuring = False
        with contextlib.suppress(RuntimeError):
            self._lock.release()

    def next_sequence(self) -> int:
        """返回下一个设备级帧序号，跨 run 单调递增"""
        self._sequence += 1
        return self._sequence


def estimate_timeout(
    cfg: MeasurementConfig,
    frames: int = 1,
    *,
    explicit: float | None = None,
) -> float:
    """返回等待超时（秒）

    - 直接传入超时参数时直接采用，必须 > 0
    - 软件触发：按 ``积分时间 * 平均 * 帧数`` 外推并留余量
    - 非软件触发：等待时长由外部事件决定，无法估算，必须传入参数
    """
    if explicit is not None:
        value = float(explicit)
        if value <= 0:
            raise InvalidParameterError(f"timeout_s 必须为正，收到 {value}")
        return value
    if not cfg.trigger.is_software:
        raise InvalidParameterError("非软件触发下无法估算超时，请显式传入 timeout_s")
    per_frame_s = cfg.integration_ms / 1000.0 * max(1, int(cfg.averages))
    # 设备实际完成一帧可能接近 2 倍积分时间，包含首帧丢弃、预扫描、USB 缓冲等
    # 超时只是等待上限，调宽松不会拖慢正常采集
    return max(_MIN_TIMEOUT_S, per_frame_s * max(1, int(frames)) * _SAFETY_FACTOR + _MARGIN_S)


def _safe_stop(port: AcquisitionPort) -> None:
    with contextlib.suppress(Exception):
        port.stop()


def wait_ready(port: AcquisitionPort, timeout_s: float) -> None:
    """轮询直到测量就绪，超时或轮询报错时抛异常 :class:`MeasurementTimeoutError`

    轮询间隔从 2 ms 起指数退避到 50 ms
    """
    deadline = time.monotonic() + timeout_s
    interval = _POLL_INITIAL_S
    while True:
        try:
            ready = bool(port.poll_ready())
        except AvaError:
            _safe_stop(port)
            raise
        if ready:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _safe_stop(port)
            raise MeasurementTimeoutError(
                f"等待测量完成超过 {timeout_s:.1f}s；已尝试停止测量。"
                "若积分时间很长请调大 timeout_s。"
            )
        time.sleep(min(interval, remaining))
        interval = min(interval * _POLL_BACKOFF, _POLL_MAX_S)


def grab_frame(
    port: AcquisitionPort,
    cfg: MeasurementConfig,
    wavelengths: np.ndarray,
    *,
    sequence: int,
    raw: bool = False,
    saturated_mask: bool = False,
) -> Spectrum:
    """读取一帧 :class:`Spectrum` 光谱数据"""
    n = cfg.num_pixels
    data = port.read_frame(n)
    counts = np.asarray(data.spectrum, dtype=np.float64)

    mask = None
    if saturated_mask:
        mask = np.asarray(port.read_saturated(n), dtype=bool)

    raw_counts = None
    raw_averages = None
    if raw:
        raw_data = port.read_raw_frame(n)
        raw_counts = np.asarray(raw_data.spectrum, dtype=np.float64)
        raw_averages = int(raw_data.averages)

    return Spectrum(
        wavelengths=wavelengths,
        counts=counts,
        timestamp_ticks=int(data.timestamp),
        integration_ms=cfg.integration_ms,
        averages=cfg.averages,
        start_pixel=cfg.start_pixel,
        stop_pixel=cfg.stop_pixel,
        saturation_level=cfg.saturation_level,
        sequence=sequence,
        host_time=time.monotonic(),
        saturated_mask=mask,
        raw_counts=raw_counts,
        raw_averages=raw_averages,
    )


class MeasurementRun:
    """单次测量的运行时序

    ``begin → measure(nmsr) → wait/grab → stop + release``

    也是上下文管理器，进入时占用租约并启动测量，退出时停止测量并释放租约
    """

    def __init__(
        self,
        lease: DeviceLease,
        config: MeasurementConfig,
        wavelengths: np.ndarray,
        *,
        timeout_s: float,
        nmsr: int = 1,
        raw: bool = False,
        saturated_mask: bool = False,
    ) -> None:
        self._lease = lease
        self._config = config
        self._wavelengths = wavelengths
        self._timeout_s = timeout_s
        self._nmsr = int(nmsr)
        self._raw = raw
        self._saturated_mask = saturated_mask
        self._started = False

    def __enter__(self) -> Self:
        lease = self._lease
        lease.begin()
        try:
            lease.acquisition().start(self._nmsr)
        except BaseException:
            lease.end()
            raise
        self._started = True
        return self

    def _frame(self) -> Spectrum:
        lease = self._lease
        return grab_frame(
            lease.acquisition(),
            self._config,
            self._wavelengths,
            sequence=lease.next_sequence(),
            raw=self._raw,
            saturated_mask=self._saturated_mask,
        )

    def next_frame(self) -> Spectrum:
        """等待就绪后取回一帧（single、continuous 模式）"""
        port = self._lease.acquisition()
        wait_ready(port, self._timeout_s)
        return self._frame()

    def read_store_to_ram(self, n: int) -> list[Spectrum]:
        """取回 StoreToRam 的 ``n`` 帧

        遇 ``-17 ERR_NO_SPECTRA_IN_RAM`` 视为提前结束

        实际取回帧数不足 ``n`` 帧时抛 :class:`IncompleteAcquisitionError`，已读取的帧随异常抛出
        """
        # StoreToRam 只触发一次采集，无需再轮询 poll_scan
        port = self._lease.acquisition()
        wait_ready(port, self._timeout_s)

        frames: list[Spectrum] = []
        for _ in range(int(n)):
            try:
                frames.append(self._frame())
            except MeasurementError as exc:
                if getattr(exc, "code", None) == int(ErrCode.ERR_NO_SPECTRA_IN_RAM):
                    break
                raise

        if len(frames) != int(n):
            raise IncompleteAcquisitionError(
                f"请求 {n} 帧但只取回 {len(frames)} 帧"
                "（板载 RAM 容量不足时会少存，请减少帧数或缩小像素范围）",
                frames=frames,
                requested=int(n),
            )
        return frames

    def stop(self) -> None:
        """停止测量"""
        if not self._started:
            return
        with contextlib.suppress(Exception):
            self._lease.acquisition().stop()

    def __exit__(self, *exc: object) -> None:
        try:
            self.stop()
        finally:
            if self._started:
                self._started = False
                self._lease.end()
