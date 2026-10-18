"""带参考谱生命周期的测量会话

- :class:`MeasurementSession` 持有设备面与参考谱，每次测量返回 :class:`Measurement`；
- :class:`Measurement` 同时带**仪器原始谱**（``spectrum``）与**已扣暗谱**
  （``corrected``），原始谱永远不会丢；
- 提示只以数据形式给出（``status.message``），库不阻塞、不弹窗；``policy="strict"``
  时才改为抛 :class:`~.reference.ReferenceInvalidError`，适合全自动测量；
- 现有自由函数（``dark_corrected`` / ``transmittance`` …）保留为裸谱入口，本 module
  只是它们之上的编排壳。
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from ..core.errors import InvalidParameterError
from ..core.models import Spectrum
from .reference import (
    DEFAULT_MAX_AGE_HOURS,
    Reference,
    ReferenceInvalidError,
    ReferencePair,
    ReferenceStatus,
    capture_reference,
)
from .spectral import (
    MIN_REFERENCE_FRACTION,
    RelativeResult,
    dark_corrected,
)

if TYPE_CHECKING:
    from ._device import DeviceAccess

__all__ = [
    "Measurement",
    "MeasurementSession",
    "SessionStatus",
    "StalePolicy",
]

#: 参考谱失效时的处理策略
#:
#: - ``"warn"``（默认）：照常测量并在状态里标记
#: - ``"strict"``：不可用时直接抛 :class:`ReferenceInvalidError`
#: - ``"off"``：不检查，只记录状态
StalePolicy = Literal["warn", "strict", "off"]

_POLICIES = ("warn", "strict", "off")


@dataclass(frozen=True, slots=True)
class SessionStatus:
    """两张参考谱的可用性"""

    #: 暗谱状态，``None`` 表示还没采集过
    dark: ReferenceStatus | None = None
    #: 亮谱状态，``None`` 表示还没采集过
    bright: ReferenceStatus | None = None
    #: 两张参考谱互相不匹配的原因
    pair: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """暗谱可用于扣暗"""
        return self.dark is not None and self.dark.ok

    @property
    def relative_ok(self) -> bool:
        """暗谱和亮谱都可用且互相匹配，透射比、吸光度的前提"""
        return self.ok and self.bright is not None and self.bright.ok and not self.pair

    @property
    def reasons(self) -> tuple[str, ...]:
        out: list[str] = []
        if self.dark is None:
            out.append("尚未采集 dark 参考谱")
        else:
            out.extend(f"dark: {reason}" for reason in self.dark.reasons)
        if self.bright is not None:
            out.extend(f"bright: {reason}" for reason in self.bright.reasons)
        out.extend(f"参考谱对: {reason}" for reason in self.pair)
        return tuple(out)

    @property
    def message(self) -> str:
        if not self.reasons:
            return "参考谱可用"
        return "⚠ 建议重新采集参考谱：" + "；".join(self.reasons)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "relative_ok": self.relative_ok,
            "reasons": list(self.reasons),
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class Measurement:
    """一次测量的结果

    :param spectrum: 原始输出
    :param corrected: 满足暗背景扣除时输出减去背景的光谱
    :param status: 参考谱可用性状态
    """

    spectrum: Spectrum
    corrected: Spectrum | None
    status: SessionStatus


class MeasurementSession:
    """测量会话

    用法::

        with Spectrometer() as spec:
            session = MeasurementSession(spec)
            session.capture_dark(frames=20)     # 遮光
            session.capture_bright(frames=5)    # 白板

            m = session.measure()
            m.spectrum                           # 仪器原始谱
            m.corrected                          # 已扣暗
            if not m.status.ok:                  # 提示重采（不阻塞）
                print(m.status.message)
            session.absorbance(m)                # 吸光度

    顺序：先定好积分时间，如 ``auto_exposure()``，再采参考谱。
    改积分时间后参考谱会变成 stale，``corrected`` 随即为 ``None``，状态里会给出原因。
    """

    def __init__(
        self,
        device: DeviceAccess,
        *,
        policy: StalePolicy = "warn",
        max_age_hours: float | None = DEFAULT_MAX_AGE_HOURS,
    ) -> None:
        if policy not in _POLICIES:
            raise InvalidParameterError(f"policy 只能是 {_POLICIES}，收到 {policy!r}")
        self._device = device
        self._policy: StalePolicy = policy
        self._max_age_hours = max_age_hours
        self._dark: Reference | None = None
        self._bright: Reference | None = None

    # %% 访问

    @property
    def device(self) -> DeviceAccess:
        """底层设备，用于修改配置等"""
        return self._device

    @property
    def policy(self) -> StalePolicy:
        return self._policy

    @property
    def dark(self) -> Reference | None:
        return self._dark

    @dark.setter
    def dark(self, value: Reference | None) -> None:
        """使用已保存的暗谱，传入 ``None`` 则清除"""
        self._dark = self._checked(value, "dark")

    @property
    def bright(self) -> Reference | None:
        return self._bright

    @bright.setter
    def bright(self, value: Reference | None) -> None:
        """使用已保存的亮谱，传入 ``None`` 则清除"""
        self._bright = self._checked(value, "bright")

    @staticmethod
    def _checked(value: Reference | None, expect: str) -> Reference | None:
        if value is None:
            return None
        if not isinstance(value, Reference):
            raise TypeError("参考谱必须是 features.reference.Reference")
        if value.kind != expect:
            raise InvalidParameterError(
                f"{expect} 只能装 {expect} 参考谱，收到 kind={value.kind!r}"
            )
        return value

    # %% 采集

    def capture_dark(
        self,
        *,
        frames: int = 1,
        interval_s: float = 0.0,
        timeout_s: float | None = None,
    ) -> Reference:
        """在当前配置下采集暗谱并保存"""
        self._dark = capture_reference(
            self._device,
            "dark",
            frames=frames,
            interval_s=interval_s,
            timeout_s=timeout_s,
        )
        return self._dark

    def capture_bright(
        self,
        *,
        frames: int = 1,
        interval_s: float = 0.0,
        timeout_s: float | None = None,
    ) -> Reference:
        """在当前配置下采集亮谱并保存"""
        self._bright = capture_reference(
            self._device,
            "bright",
            frames=frames,
            interval_s=interval_s,
            timeout_s=timeout_s,
        )
        return self._bright

    # %% 状态

    def status(self, *, now: datetime | None = None) -> SessionStatus:
        """当前参考谱是否还适用于设备的当前配置"""
        cfg = self._device.measurement_config
        serial = self._device.info.serial
        dark = (
            self._dark.status(
                cfg,
                serial=serial,
                max_age_hours=self._max_age_hours,
                now=now,
            )
            if self._dark is not None
            else None
        )
        bright = (
            self._bright.status(
                cfg,
                serial=serial,
                max_age_hours=self._max_age_hours,
                now=now,
            )
            if self._bright is not None
            else None
        )
        pair = (
            tuple(ReferencePair.problems(self._dark, self._bright))
            if self._dark is not None and self._bright is not None
            else ()
        )
        return SessionStatus(dark=dark, bright=bright, pair=pair)

    # %% 测量

    def measure(self, *, timeout_s: float | None = None) -> Measurement:
        """采集一帧"""
        status = self.status()
        if self._policy == "strict" and not status.ok:
            raise ReferenceInvalidError(f"参考谱不可用：{status.message}")
        spectrum = self._device.measure(timeout_s=timeout_s)
        # 只在暗谱的测量条件和当前配置一致时才计算
        corrected: Spectrum | None = None
        if self._dark is not None and self._dark.conditions.matches(
            self._device.measurement_config
        ):
            corrected = dark_corrected(spectrum, self._dark.spectrum)
        return Measurement(spectrum=spectrum, corrected=corrected, status=status)

    def measure_many(
        self,
        n: int,
        *,
        interval_s: float = 0.0,
        timeout_s: float | None = None,
    ) -> Iterator[Measurement]:
        """逐帧采集 ``n`` 帧"""
        count = int(n)
        if count < 1:
            raise InvalidParameterError(f"n 必须 >= 1，收到 {n}")
        for i in range(count):
            yield self.measure(timeout_s=timeout_s)
            if interval_s > 0 and i < count - 1:
                time.sleep(float(interval_s))

    # %% 相对量

    def transmittance(
        self,
        measurement: Measurement,
        *,
        min_reference_fraction: float = MIN_REFERENCE_FRACTION,
    ) -> RelativeResult:
        """透射比 ``(S - D) / (R - D)``，需要互相匹配的 dark 和 bright"""
        pair = self._require_relative()
        return pair.transmittance(
            measurement.spectrum,
            min_reference_fraction=min_reference_fraction,
        )

    def absorbance(
        self,
        measurement: Measurement,
        *,
        min_reference_fraction: float = MIN_REFERENCE_FRACTION,
    ) -> RelativeResult:
        """吸光度 ``-log10(T)``"""
        return self.transmittance(
            measurement, min_reference_fraction=min_reference_fraction
        ).absorbance()

    def reflectance(
        self,
        measurement: Measurement,
        *,
        min_reference_fraction: float = MIN_REFERENCE_FRACTION,
    ) -> RelativeResult:
        """相对反射率"""
        pair = self._require_relative()
        return pair.reflectance(
            measurement.spectrum,
            min_reference_fraction=min_reference_fraction,
        )

    def _require_relative(self) -> ReferencePair:
        if self._dark is None or self._bright is None:
            raise ReferenceInvalidError("透射比 / 吸光度需要 dark 与 bright 两张参考谱")
        pair = ReferencePair(self._dark, self._bright)
        if self._policy == "strict":
            status = self.status()
            if not status.relative_ok:
                raise ReferenceInvalidError(f"参考谱不可用：{status.message}")
        return pair
