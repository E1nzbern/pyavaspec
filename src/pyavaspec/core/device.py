"""光谱仪操作 API"""

from __future__ import annotations

import atexit
import contextlib
import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from typing import Any, Self

import numpy as np

from .._lowlevel import AvaSpecx
from .._lowlevel._types import DeviceStatus, Port, SmoothingModel
from . import _acquisition
from ._bridge import (
    as_wavelength_slice,
    identity_from_struct,
    meas_to_struct,
    status_from_code,
)
from ._driver import DriverAdapter
from ._snapshot import DeviceSnapshot, read_config, read_device
from ._validate import validate_config, validate_stray_light_factor
from .errors import (
    AvaError,
    DeviceBusyError,
    DeviceNotFoundError,
    DeviceNotOpenError,
    DeviceWriteError,
    InvalidParameterError,
    InvalidStateError,
    MeasurementInProgressError,
)
from .io import DeviceIO
from .models import (
    DeviceConfig,
    DeviceIdentity,
    DeviceInfo,
    MeasurementConfig,
    Spectrum,
    Trigger,
    replace_present,
)

__all__ = [
    "DriverSession",
    "Spectrometer",
    "SpectrumStream",
    "list_devices",
    "status_by_serial",
]

#: 进程退出时仍打开的实例，用于兜底清理
_OPEN_DEVICES: set[Spectrometer] = set()


def _close_open_devices() -> None:
    """解释器退出前停止采集、释放设备句柄，避免设备停留在占用状态"""
    for spec in list(_OPEN_DEVICES):
        with contextlib.suppress(Exception):
            spec.close()


atexit.register(_close_open_devices)


class Spectrometer:
    """AvaSpec 光谱仪的高层 API

    推荐用法::

        with Spectrometer() as spec:
            spec.configure(integration_ms=100, averages=2)
            frame = spec.measure()

    非线程安全，一个实例同一时刻只允许一个采集调用
    """

    def __init__(
        self,
        serial: str | None = None,
        *,
        session: DriverSession | None = None,
        dll_path: str | None = None,
        port: int | Port | None = None,
    ) -> None:
        if session is not None and (dll_path is not None or port is not None):
            raise ValueError("session 与 dll_path/port 互斥：借用会话时不应再指定 DLL 或端口")
        if session is not None and not isinstance(session, DriverSession):
            raise TypeError("session 必须是 core.device.DriverSession")
        self._serial = serial
        self._owns_session = session is None
        self._session: DriverSession = (
            session
            if session is not None
            else DriverSession(dll_path, port=Port.USB if port is None else Port(port))
        )

        self._open = False
        self._lease = _acquisition.DeviceLease()

        self._snapshot: DeviceSnapshot | None = None
        self._meas_config: MeasurementConfig | None = None
        self._wavelengths: np.ndarray | None = None
        self._io: DeviceIO | None = None

    # %% 生命周期

    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> Self:
        """打开设备，失败时自动回收句柄和租约"""
        if self._open:
            return self
        session = self._session
        if not self._owns_session and not session.is_open:
            raise InvalidStateError(
                "借用的 DriverSession 尚未打开：请先在其 owner 处 open()，"
                "例如 `with DriverSession() as session: Spectrometer(session=session)`"
            )
        try:
            if self._owns_session:
                session.open()
            driver = session.driver
            identities = driver.list_devices()
            target = self._select(identities)
            handle = self._activate(target)
            self._lease.attach(driver.bind(handle, self._require_session_alive))

            identity = identity_from_struct(target)
            snapshot = read_device(self._lease.reads(), identity)

            self._snapshot = snapshot
            self._wavelengths = snapshot.wavelengths
            self._io = DeviceIO(
                self._lease.io(),
                temperature_fit=snapshot.temperature_fit,
            )

            default = MeasurementConfig(
                start_pixel=0,
                stop_pixel=max(0, snapshot.info.num_pixels - 1),
                integration_ms=10.0,
                averages=1,
                high_res_adc=True,
                saturation_detection=True,
            )
            self._apply_config(default)
            self._open = True
            _OPEN_DEVICES.add(self)
        except Exception:
            self._abort_open()
            raise
        return self

    def close(self) -> None:
        """关闭设备（幂等）。清理动作屏蔽异常，避免触碰可能失效的句柄。"""
        _OPEN_DEVICES.discard(self)
        if not self._open:
            return
        self._open = False
        try:
            self._lease.release()
        finally:
            self._reset_cache()
            if self._owns_session:
                with contextlib.suppress(Exception):
                    self._session.close()

    def __enter__(self) -> Self:
        return self.open()

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        state = "已打开" if self._open else "未打开"
        serial = self._snapshot.info.serial if self._snapshot is not None else self._serial
        return f"<Spectrometer {state} 序列号={serial!r}>"

    # %% 信息

    @property
    def info(self) -> DeviceInfo:
        self._require_open()
        return self._require_snapshot().info

    @property
    def config(self) -> DeviceConfig:
        self._require_open()
        return self._require_snapshot().config

    @property
    def num_pixels(self) -> int:
        self._require_open()
        return self._require_snapshot().info.num_pixels

    @property
    def wavelengths(self) -> np.ndarray:
        """波长 nm 列表"""
        self._require_open()
        return self._require_snapshot().wavelengths

    @property
    def measurement_config(self) -> MeasurementConfig:
        self._require_open()
        return self._require_config()

    @property
    def saturation_level(self) -> int:
        self._require_open()
        return self._require_config().saturation_level

    @property
    def io(self) -> DeviceIO:
        self._require_open()
        assert self._io is not None
        return self._io

    def refresh_config(self) -> DeviceConfig:
        """重新读取设备配置 :class:`DeviceConfig`

        数据来自 EEPROM：像素数、传感器类型、波长系数、校准数据等。
        与 :meth:`configure` / :meth:`apply_config` 的运行时 :class:`MeasurementConfig`
        （积分时间、平均、触发等）无关。

        本方法只用于在外部改动后刷新只读配置信息
        """
        self._require_open()
        self._snapshot = replace(self._require_snapshot(), config=read_config(self._lease.reads()))
        return self._snapshot.config

    # %% 配置

    def configure(
        self,
        *,
        integration_ms: float | None = None,
        averages: int | None = None,
        pixels: tuple[int, int] | None = None,
        smoothing_pixels: int | None = None,
        smoothing_model: SmoothingModel | int | None = None,
        high_res_adc: bool | None = None,
        saturation_detection: bool | None = None,
        dynamic_dark: bool | None = None,
        forget_percentage: int | None = None,
        store_to_ram: int | None = None,
        integration_delay_ticks: int | None = None,
        prescan: bool | None = None,
        trigger: Trigger | None = None,
    ) -> MeasurementConfig:
        """集合修改测量参数一次性下发

        ``None`` 表示保持当前值；``pixels`` 是 ``(start_pixel, stop_pixel)`` 的别名。

        下发失败时内部保持原值
        """
        self._require_open()
        current = self._require_config()
        start, stop = current.start_pixel, current.stop_pixel
        if pixels is not None:
            start, stop = pixels[0], pixels[1]
        candidate = replace_present(
            current,
            {
                "start_pixel": start,
                "stop_pixel": stop,
                "integration_ms": integration_ms,
                "averages": averages,
                "smoothing_pixels": smoothing_pixels,
                "smoothing_model": smoothing_model,
                "high_res_adc": high_res_adc,
                "saturation_detection": saturation_detection,
                "dynamic_dark": dynamic_dark,
                "forget_percentage": forget_percentage,
                "store_to_ram": store_to_ram,
                "integration_delay_ticks": integration_delay_ticks,
                "prescan": prescan,
                "trigger": trigger,
            },
        )
        return self.apply_config(candidate)

    def apply_config(self, config: MeasurementConfig) -> MeasurementConfig:
        """完整覆盖测量配置，可用于保存复现实验参数"""
        self._require_open()
        if self._lease.measuring:
            raise MeasurementInProgressError("测量进行中不能修改测量配置，请先 stop()")
        if not isinstance(config, MeasurementConfig):
            raise TypeError("config 必须是 core.models.MeasurementConfig")
        self._apply_config(config)
        return config

    # %% 采集

    def measure(
        self,
        *,
        timeout_s: float | None = None,
        raw: bool = False,
        saturated_mask: bool = False,
    ) -> Spectrum:
        """采集一帧光谱数据"""
        lease = self._require_lease()
        cfg = self._require_config()
        if cfg.store_to_ram:
            raise InvalidParameterError("当前配置启用了 store_to_ram，请使用 acquire_to_ram()")
        assert self._wavelengths is not None
        timeout = _acquisition.estimate_timeout(cfg, 1, explicit=timeout_s)
        with _acquisition.MeasurementRun(
            lease,
            cfg,
            self._wavelengths,
            timeout_s=timeout,
            raw=raw,
            saturated_mask=saturated_mask,
        ) as run:
            return run.next_frame()

    def measure_many(
        self,
        n: int,
        *,
        interval_s: float = 0.0,
        timeout_s: float | None = None,
        raw: bool = False,
        saturated_mask: bool = False,
    ) -> Iterator[Spectrum]:
        """逐帧采集 ``n`` 帧"""
        if n < 1:
            raise InvalidParameterError(f"n 必须 >= 1，收到 {n}")
        for i in range(int(n)):
            yield self.measure(timeout_s=timeout_s, raw=raw, saturated_mask=saturated_mask)
            if interval_s > 0 and i < n - 1:
                time.sleep(float(interval_s))

    def stream(
        self,
        *,
        timeout_s: float | None = None,
        raw: bool = False,
        saturated_mask: bool = False,
    ) -> SpectrumStream:
        """连续采集，返回 :class:`SpectrumStream`

        推荐写法::

            with spec.stream() as frames:
                for frame in frames:
                    ...
        """
        lease = self._require_lease()
        cfg = self._require_config()
        assert self._wavelengths is not None
        timeout = _acquisition.estimate_timeout(cfg, 1, explicit=timeout_s)
        return SpectrumStream(
            lease,
            cfg,
            self._wavelengths,
            timeout,
            raw=raw,
            saturated_mask=saturated_mask,
        )

    def acquire_to_ram(
        self,
        n: int,
        *,
        timeout_s: float | None = None,
        raw: bool = False,
        saturated_mask: bool = False,
    ) -> list[Spectrum]:
        """使用光谱仪板载 RAM 批量采集 ``n`` 帧

        ``store_to_ram=n``，结束或异常时会回退原始值，要求 ``averages == 1`` 且为软件触发
        """
        lease = self._require_lease()
        if n < 1:
            raise InvalidParameterError(f"n 必须 >= 1，收到 {n}")
        original = self._require_config()
        ram_cfg = replace(original, store_to_ram=int(n))
        assert self._wavelengths is not None
        timeout = _acquisition.estimate_timeout(ram_cfg, n, explicit=timeout_s)
        with (
            self._temporary_config(ram_cfg),
            _acquisition.MeasurementRun(
                lease,
                ram_cfg,
                self._wavelengths,
                timeout_s=timeout,
                raw=raw,
                saturated_mask=saturated_mask,
            ) as run,
        ):
            return run.read_store_to_ram(n)

    def stop(self) -> None:
        """停止当前连续、批量采集"""
        if not self._open or not self._session.is_open:
            return
        with contextlib.suppress(Exception):
            self._lease.acquisition().stop()

    def is_measuring(self) -> bool:
        return bool(self._open and self._lease.measuring)

    # %% 光谱后处理

    def suppress_stray_light(
        self,
        spectrum: Spectrum,
        *,
        multi_factor: float = 0.5,
    ) -> Spectrum:
        """杂散光抑制

        ``AVS_SuppressStrayLight`` 驱动程序提供的纯软件算法处理

        :param spectrum: 待处理的帧
        :param multi_factor: 抑制强度，有效范围 0-2；
            越界抛 :class:`~pyavaspec.core.errors.InvalidParameterError`
        :return: 同 metadata 的新 :class:`Spectrum`，``counts`` 为处理后的值
        """
        self._require_open()
        if not isinstance(spectrum, Spectrum):
            raise TypeError("spectrum 必须是 core.models.Spectrum")
        factor = validate_stray_light_factor(multi_factor)
        processed = self._lease.processing().suppress_stray_light(
            np.asarray(spectrum.counts, dtype=np.float64), factor
        )
        return replace(spectrum, counts=np.asarray(processed, dtype=np.float64))

    # %% 内部

    def _select(self, identities: list[Any]) -> Any:
        if not identities:
            raise DeviceNotFoundError("未发现设备")
        if self._serial is None:
            return identities[0]
        for candidate in identities:
            if identity_from_struct(candidate).serial == self._serial:
                return candidate
        serials = [identity_from_struct(c).serial for c in identities]
        raise DeviceNotFoundError(f"未找到序列号 {self._serial!r}；在线设备：{serials}")

    def _activate(self, identity_struct: Any) -> int:
        try:
            return int(self._session.driver.activate(identity_struct))
        except AvaError as exc:
            identity = identity_from_struct(identity_struct)
            if identity.in_use:
                raise DeviceBusyError(
                    f"设备 {identity.serial} 正被其它程序占用"
                    "请先关闭 AvaSoft 8、AvaSoftX 或其他软件"
                ) from exc
            raise DeviceNotFoundError(f"激活设备 {identity.serial} 失败：{exc}") from exc

    def _apply_config(self, cfg: MeasurementConfig) -> None:
        """校验、下发并回读确认，全部成功后才更新内部快照。

        任何一步失败都会尝试把上一次成功生效的配置重新下发给硬件
        """
        snapshot = self._require_snapshot()
        validate_config(cfg, snapshot.info.num_pixels)
        previous = self._meas_config
        try:
            self._push_config(cfg, previous)
            self._verify_config(cfg)
        except Exception:
            if previous is not None and self._lease.is_valid:
                with contextlib.suppress(Exception):
                    self._push_config(previous, cfg)
            raise
        self._meas_config = cfg
        self._wavelengths = as_wavelength_slice(snapshot.wavelengths, cfg)

    @contextlib.contextmanager
    def _temporary_config(self, cfg: MeasurementConfig) -> Iterator[None]:
        """临时下发配置，退出（含异常）时恢复原值。"""
        original = self._require_config()
        applied = False
        try:
            self._apply_config(cfg)
            applied = True
            yield
        finally:
            if applied and self._lease.is_valid:
                with contextlib.suppress(Exception):
                    self._apply_config(original)

    def _push_config(self, cfg: MeasurementConfig, current: MeasurementConfig | None) -> None:
        """把配置下发到硬件

        ``current`` 是硬件当前生效的配置，用于判断是否需要调用 prescan
        仅在打开时或 prescan 实际变化时才下发
        """
        port = self._lease.config()
        struct = meas_to_struct(cfg)
        port.set_high_res_adc(cfg.high_res_adc)
        port.prepare(struct)
        if current is None:
            if cfg.prescan:
                port.set_prescan(True)
        elif current.prescan != cfg.prescan:
            port.set_prescan(cfg.prescan)

    def _verify_config(self, cfg: MeasurementConfig) -> None:
        """回读实际测量像素数，确认配置生效"""
        expected = cfg.stop_pixel - cfg.start_pixel + 1
        actual = int(self._lease.config().read_meas_pixels())
        if actual != expected:
            raise DeviceWriteError(
                "测量配置下发后回读不一致："
                f"期望 {expected} 个像素（{cfg.start_pixel}..{cfg.stop_pixel}），"
                f"设备返回 {actual}"
            )

    def _abort_open(self) -> None:
        self._lease.release()
        self._open = False
        self._reset_cache()
        if self._owns_session:
            with contextlib.suppress(Exception):
                self._session.close()

    def _reset_cache(self) -> None:
        self._snapshot = None
        self._meas_config = None
        self._wavelengths = None
        self._io = None

    def _require_open(self) -> None:
        if not self._open:
            raise DeviceNotOpenError(
                "设备尚未打开：请使用 `with Spectrometer() as spec:` 或先调用 open()"
            )
        if not self._session.is_open:
            raise InvalidStateError(
                "底层 DriverSession 已被关闭，设备句柄已失效；请重新打开驱动会话与设备"
            )

    def _require_session_alive(self) -> None:
        """存活守卫：驱动会话仍打开。

        供 :class:`~pyavaspec.core._driver.BoundDevice` 在每次 port 调用前使用；
        ``open()`` 读取期间 ``self._open`` 尚未置位，因此这里不检查 ``self._open``。
        """
        if not self._session.is_open:
            raise InvalidStateError(
                "底层 DriverSession 已被关闭，设备句柄已失效；请重新打开驱动会话与设备"
            )

    def _require_lease(self) -> _acquisition.DeviceLease:
        """返回本设备的内部租约；设备未打开时抛语义异常。"""
        self._require_open()
        return self._lease

    def _require_config(self) -> MeasurementConfig:
        cfg = self._meas_config
        if cfg is None:
            raise InvalidStateError("测量配置尚未就绪，设备是否已打开？")
        return cfg

    def _require_snapshot(self) -> DeviceSnapshot:
        snapshot = self._snapshot
        if snapshot is None:
            raise InvalidStateError("设备快照尚未就绪，设备是否已打开？")
        return snapshot


class SpectrumStream:
    """连续采集的迭代器，可作为上下文管理器。

    推荐用法::

        with spec.stream() as stream:
            for frame in stream:
                ...
    """

    def __init__(
        self,
        lease: _acquisition.DeviceLease,
        config: MeasurementConfig,
        wavelengths: np.ndarray,
        timeout_s: float,
        *,
        raw: bool = False,
        saturated_mask: bool = False,
    ) -> None:
        self._lease = lease
        self._config = config
        self._wavelengths = wavelengths
        self._timeout_s = timeout_s
        self._raw = raw
        self._saturated_mask = saturated_mask
        self._run: _acquisition.MeasurementRun | None = None
        self._closed = False

    def __iter__(self) -> Self:
        return self

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            self.close()

    def _start(self) -> None:
        run = _acquisition.MeasurementRun(
            self._lease,
            self._config,
            self._wavelengths,
            timeout_s=self._timeout_s,
            nmsr=-1,
            raw=self._raw,
            saturated_mask=self._saturated_mask,
        )
        run.__enter__()
        self._run = run

    def __next__(self) -> Spectrum:
        if self._closed:
            raise StopIteration
        if self._run is None:
            self._start()
        run = self._run
        assert run is not None
        try:
            return run.next_frame()
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        """停止连续采集并释放测量锁"""
        if self._closed:
            return
        self._closed = True
        run = self._run
        if run is not None:
            run.__exit__(None, None, None)


# %% 驱动会话


class DriverSession:
    """进程级驱动会话。

    `AVS_Init` / `AVS_Done` 是进程级全局状态，由 :mod:`pyavaspec._lowlevel._session` 负责引用计数

    - 本类只包含驱动初始化，不涉及设备操作
    - 设备级生命周期（句柄、采集、IO）由 :class:`Spectrometer` 负责。

    用法一般是在同一会话内反复枚举 / 查询，避免每次调用都触发一次``Init`` / ``Done``::

        with DriverSession() as session:
            for device in session.list_devices():
                print(device.serial, session.get_status_by_serial(device.serial))

    每个 ``DriverSession`` 持有独立的低层租约，多个会话可以并存，底层用引用计数共享，
    线程同步由底层 ``_session`` 的锁保证。
    本类不持有设备句柄，可被多个 :class:`Spectrometer` 借用；它是 ``core`` 内唯一的驱动
    运行时租约持有者，也是唯一构造 / 关闭 ``AvaSpecx`` 的地方
    """

    def __init__(
        self,
        dll_path: str | None = None,
        *,
        port: int | Port = Port.USB,
        driver: DriverAdapter | None = None,
    ) -> None:
        if driver is not None and dll_path is not None:
            raise ValueError("driver 与 dll_path 互斥：注入驱动时不应再指定 DLL")
        self._dll_path = dll_path
        self._port = Port(port)
        self._injected = driver is not None
        self._driver: DriverAdapter | None = driver
        self._open = False
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def driver(self) -> DriverAdapter:
        """驱动适配器，供 :class:`Spectrometer` 借用共享会话。"""
        if not self._open or self._driver is None:
            raise InvalidStateError(
                "驱动会话尚未打开：请使用 `with DriverSession() as session:` 或先调用 open()"
            )
        return self._driver

    def open(self) -> Self:
        """开启驱动运行时会话"""
        with self._lock:
            if self._open:
                return self
            driver = self._driver
            if driver is None:
                driver = DriverAdapter(AvaSpecx(self._dll_path, port=int(self._port)))
                self._driver = driver
            try:
                driver.open()
            except BaseException:
                if not self._injected:
                    self._driver = None
                raise
            self._open = True
        return self

    def close(self) -> None:
        """归还会话租约"""
        with self._lock:
            if not self._open:
                return
            driver = self._driver
            self._open = False
            if not self._injected:
                # 类自行创建的实例一次性使用，通过参数输入的则保留，以便重新 open()
                self._driver = None
        if driver is not None:
            with contextlib.suppress(Exception):
                driver.close()

    def __enter__(self) -> Self:
        return self.open()

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        state = "已打开" if self._open else "未打开"
        return f"<DriverSession {state} port={int(self._port)}>"

    def list_devices(self) -> list[DeviceIdentity]:
        """在当前会话内枚举在线设备，不激活设备"""
        items = self.driver.list_devices()
        return [identity_from_struct(item) for item in items]

    def get_status_by_serial(self, serial: str) -> DeviceStatus:
        """在当前会话内按序列号查询设备状态，不激活设备"""
        return status_from_code(self.driver.get_status(serial))


# %% 模块级函数


def list_devices(
    dll_path: str | None = None,
    *,
    port: int | Port = Port.USB,
    session: DriverSession | None = None,
) -> list[DeviceIdentity]:
    """枚举在线设备，不激活设备

    底层 `AVS_GetList` 要求先执行 ``AVS_Init`` ，比较重，虽然不是设备初始化

    :param session: 已打开的 :class:`DriverSession`，传入时复用；为 ``None`` 时临时借用一次会话
    """
    if session is not None:
        return session.list_devices()
    with DriverSession(dll_path, port=port) as temp:
        return temp.list_devices()


def status_by_serial(
    serial: str,
    dll_path: str | None = None,
    *,
    port: int | Port = Port.USB,
    session: DriverSession | None = None,
) -> DeviceStatus:
    """按序列号查询设备状态，不激活设备

    :param port: 设备端口类型，USB / 以太网，仅在未传入 ``session`` 时用于临时借用会话。
    :param session: 已打开的 :class:`DriverSession`，传入时复用它，``port`` 被忽略。
    """
    if session is not None:
        return session.get_status_by_serial(serial)
    with DriverSession(dll_path, port=port) as temp:
        return temp.get_status_by_serial(serial)
