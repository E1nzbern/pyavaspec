"""暗谱 / 亮谱参考谱的采集、有效期与持久化。

一张参考谱 = 一帧 :class:`~pyavaspec.core.models.Spectrum` + 采集时的
**辐射条件**（:class:`ReferenceConditions`）+ 元信息。它只在辐射条件一致且不过期时
才可用于后续测量。

- **模型与判定**：:class:`Reference` / :class:`ReferenceConditions` /
  :class:`ReferenceStatus`，以及版本化 JSON 持久化；
- **采集编排**（只消费 :class:`~pyavaspec.features._device.DeviceAccess`）：
  :func:`capture_reference` / :func:`check_reference`。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from ..core import SmoothingModel
from ..core.errors import AvaError, InvalidParameterError
from ..core.models import MeasurementConfig, Spectrum
from ._conditions import require_compatible
from .averaging import average_frames
from .spectral import (
    MIN_REFERENCE_FRACTION,
    RelativeResult,
    relative_reflectance,
    transmittance,
)

if TYPE_CHECKING:
    from ._device import DeviceAccess

__all__ = [
    "DEFAULT_MAX_AGE_HOURS",
    "REFERENCE_FORMAT",
    "Reference",
    "ReferenceConditions",
    "ReferenceInvalidError",
    "ReferencePair",
    "ReferenceStatus",
    "capture_reference",
    "check_reference",
]

REFERENCE_FORMAT = "pyavaspec-reference/1"
#: 参考谱默认过期阈值（小时）
DEFAULT_MAX_AGE_HOURS = 24.0

ReferenceKind = Literal["dark", "bright"]


class ReferenceInvalidError(AvaError):
    """参考谱与当前测量不匹配或已过期"""


def _smoothing_name(model: SmoothingModel | int) -> str:
    """平滑模型的可读名，未定义则返回数字"""
    return model.name if isinstance(model, SmoothingModel) else str(model)


@dataclass(frozen=True, slots=True)
class ReferenceConditions:
    """决定参考谱能否复用的辐射条件"""

    integration_ms: float
    averages: int
    start_pixel: int
    stop_pixel: int
    high_res_adc: bool
    smoothing_pixels: int = 0
    smoothing_model: SmoothingModel | int = SmoothingModel.AVERAGE

    @classmethod
    def from_config(cls, cfg: MeasurementConfig) -> ReferenceConditions:
        """从测量配置提取辐射条件"""
        return cls(
            integration_ms=float(cfg.integration_ms),
            averages=int(cfg.averages),
            start_pixel=int(cfg.start_pixel),
            stop_pixel=int(cfg.stop_pixel),
            high_res_adc=bool(cfg.high_res_adc),
            smoothing_pixels=int(cfg.smoothing_pixels),
            smoothing_model=cfg.smoothing_model,
        )

    def mismatches(self, cfg: MeasurementConfig) -> list[str]:
        """与当前配置的差异，积分时间是第一位"""
        return self.differences(self.from_config(cfg))

    def differences(self, other: ReferenceConditions) -> list[str]:
        """与另一份辐射条件的差异"""
        out: list[str] = []
        if abs(self.integration_ms - other.integration_ms) >= 1e-9:
            out.append(f"积分时间 {self.integration_ms:g} → {other.integration_ms:g} ms")
        if self.averages != other.averages:
            out.append(f"平均次数 {self.averages} → {other.averages}")
        if (self.start_pixel, self.stop_pixel) != (
            other.start_pixel,
            other.stop_pixel,
        ):
            out.append(
                f"像素范围 {self.start_pixel}:{self.stop_pixel} → "
                f"{other.start_pixel}:{other.stop_pixel}"
            )
        if self.high_res_adc != other.high_res_adc:
            out.append(f"ADC 位数 高分辨率={self.high_res_adc} → {other.high_res_adc}")
        if self.smoothing_pixels != other.smoothing_pixels:
            out.append(f"平滑像素 {self.smoothing_pixels} → {other.smoothing_pixels}")
        if self.smoothing_model != other.smoothing_model:
            out.append(
                f"平滑模型 {_smoothing_name(self.smoothing_model)} → "
                f"{_smoothing_name(other.smoothing_model)}"
            )
        return out

    def matches(self, cfg: MeasurementConfig) -> bool:
        """辐射条件是否与当前配置一致"""
        return not self.mismatches(cfg)


@dataclass(frozen=True, slots=True)
class ReferenceStatus:
    """参考谱可用性状态"""

    kind: str
    ok: bool
    reasons: tuple[str, ...]
    age: timedelta

    @property
    def age_hours(self) -> float:
        return self.age.total_seconds() / 3600.0

    @property
    def message(self) -> str:
        if self.ok:
            return f"{self.kind} 参考谱可用（{self.age_hours:.1f} 小时前采集）"
        return (
            f"建议重新保存 {self.kind} 参考谱："
            + "；".join(self.reasons)
            + "｜Dark may not be up to date, e.g. Integration time has "
            "changed"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ok": self.ok,
            "age_hours": round(self.age_hours, 3),
            "reasons": list(self.reasons),
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class Reference:
    """参考谱"""

    kind: ReferenceKind
    spectrum: Spectrum
    conditions: ReferenceConditions
    serial: str = ""
    created: datetime = field(default_factory=lambda: datetime.now(UTC))
    frames: int = 1

    def __post_init__(self) -> None:
        if self.kind not in ("dark", "bright"):
            raise InvalidParameterError(f"kind 只能是 'dark' 或 'bright'，收到 {self.kind!r}")
        if self.created.tzinfo is None:
            object.__setattr__(self, "created", self.created.replace(tzinfo=UTC))
        object.__setattr__(self, "frames", int(self.frames))

    # %% 有效性

    def age(self, *, now: datetime | None = None) -> timedelta:
        """距离采集的时间"""
        return (now or datetime.now(UTC)) - self.created

    def _serial_mismatch(self, serial: str | None) -> str | None:
        """参考谱不是当前设备采集的，两台仪器的暗谱不能互相替代"""
        if serial is None or not self.serial or serial == self.serial:
            return None
        return f"来自设备 {self.serial}，当前设备 {serial}"

    def status(
        self,
        cfg: MeasurementConfig,
        *,
        serial: str | None = None,
        max_age_hours: float | None = DEFAULT_MAX_AGE_HOURS,
        now: datetime | None = None,
    ) -> ReferenceStatus:
        """
        返回可用性状态

        :param serial: 传入当前设备序列号时会检查参考谱是否来自这台设备
        :param max_age_hours: ``None`` 表示只比对辐射条件
        """
        reasons = list(self.conditions.mismatches(cfg))
        device_reason = self._serial_mismatch(serial)
        if device_reason is not None:
            reasons.insert(0, device_reason)
        age = self.age(now=now)
        if max_age_hours is not None and age.total_seconds() / 3600.0 > max_age_hours:
            reasons.append(
                f"距采集 {age.total_seconds() / 3600.0:.1f} 小时 > 阈值 {max_age_hours:g} 小时"
            )
        return ReferenceStatus(kind=self.kind, ok=not reasons, reasons=tuple(reasons), age=age)

    def validate(
        self,
        cfg: MeasurementConfig,
        *,
        serial: str | None = None,
        max_age_hours: float | None = DEFAULT_MAX_AGE_HOURS,
        allow_expired: bool = False,
        now: datetime | None = None,
    ) -> None:
        """不匹配、过期时抛 :class:`ReferenceInvalidError`"""
        status = self.status(cfg, serial=serial, max_age_hours=max_age_hours, now=now)
        if status.ok:
            return
        if (
            allow_expired
            and self._serial_mismatch(serial) is None
            and not self.conditions.mismatches(cfg)
        ):
            # 只是过期但是来源和条件都匹配时，如果用户允许则可用
            return
        raise ReferenceInvalidError(f"{self.kind} 参考谱不可用：{'；'.join(status.reasons)}")

    # %% 序列化

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": REFERENCE_FORMAT,
            "kind": self.kind,
            "created": self.created.isoformat(),
            "serial": self.serial,
            "frames": self.frames,
            "conditions": asdict(self.conditions),
            "spectrum": self.spectrum.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Reference:
        if data.get("format") != REFERENCE_FORMAT:
            raise InvalidParameterError(
                f"不是 {REFERENCE_FORMAT} 格式（读到 {data.get('format')!r}）"
            )
        return cls(
            kind=data["kind"],
            spectrum=Spectrum.from_dict(data["spectrum"]),
            conditions=ReferenceConditions(**data["conditions"]),
            serial=data.get("serial", ""),
            created=datetime.fromisoformat(data["created"]),
            frames=int(data.get("frames", 1)),
        )

    def save(self, path: str | os.PathLike[str]) -> str:
        """写入 JSON，返回路径"""
        target = os.fspath(path)
        parent = os.path.dirname(os.path.abspath(target))
        os.makedirs(parent, exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, ensure_ascii=False, indent=1)
        return target

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> Reference:
        """读取 :meth:`save` 写出的 JSON"""
        with open(path, encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))


# %% 参考谱配对


@dataclass(frozen=True, slots=True)
class ReferencePair:
    """
    一对互相匹配的暗谱、亮谱

    构造成功后每帧只需要比较当前配置 :meth:`statuses`，参考谱是可信的，每次只需传当前谱；
    两者不匹配时抛 :class:`~pyavaspec.core.errors.InvalidParameterError`。
    """

    dark: Reference
    bright: Reference

    def __post_init__(self) -> None:
        """构造时校验种类、设备、测量条件"""
        problems = self.problems(self.dark, self.bright)
        if problems:
            raise InvalidParameterError("；".join(problems))

    @staticmethod
    def problems(dark: Reference, bright: Reference) -> list[str]:
        """两张参考谱能否配对"""
        out: list[str] = []
        if dark.kind != "dark":
            out.append(f"dark 位置收到 kind={dark.kind!r}")
        if bright.kind != "bright":
            out.append(f"bright 位置收到 kind={bright.kind!r}")
        if dark.serial and bright.serial and dark.serial != bright.serial:
            out.append(f"两张参考谱来自不同设备：{dark.serial} / {bright.serial}")
        try:
            require_compatible(dark.spectrum, bright.spectrum)
        except InvalidParameterError as exc:
            out.append(str(exc))
        out.extend(dark.conditions.differences(bright.conditions))
        return out

    def statuses(
        self,
        cfg: MeasurementConfig,
        *,
        serial: str | None = None,
        max_age_hours: float | None = DEFAULT_MAX_AGE_HOURS,
        now: datetime | None = None,
    ) -> tuple[ReferenceStatus, ReferenceStatus]:
        """
        分别返回暗谱、亮谱对当前配置的可用性

        :return: (暗, 亮)
        """
        return (
            self.dark.status(cfg, serial=serial, max_age_hours=max_age_hours, now=now),
            self.bright.status(cfg, serial=serial, max_age_hours=max_age_hours, now=now),
        )

    # %% 相对量

    def transmittance(
        self,
        sample: Spectrum,
        *,
        min_reference_fraction: float = MIN_REFERENCE_FRACTION,
    ) -> RelativeResult:
        """透射比 ``(S - D) / (R - D)``"""
        return transmittance(
            sample,
            self.dark.spectrum,
            self.bright.spectrum,
            min_reference_fraction=min_reference_fraction,
        )

    def absorbance(
        self,
        sample: Spectrum,
        *,
        min_reference_fraction: float = MIN_REFERENCE_FRACTION,
    ) -> RelativeResult:
        """吸光度 ``-log10(T)``"""
        return self.transmittance(
            sample, min_reference_fraction=min_reference_fraction
        ).absorbance()

    def reflectance(
        self,
        sample: Spectrum,
        *,
        min_reference_fraction: float = MIN_REFERENCE_FRACTION,
    ) -> RelativeResult:
        """相对反射率，与透射比逻辑相同"""
        return relative_reflectance(
            sample,
            self.dark.spectrum,
            self.bright.spectrum,
            min_reference_fraction=min_reference_fraction,
        )


# %% 采集编排


def capture_reference(
    device: DeviceAccess,
    kind: ReferenceKind = "dark",
    *,
    frames: int = 1,
    interval_s: float = 0.0,
    timeout_s: float | None = None,
) -> Reference:
    """采集一张参考谱

    :param device: 采集设备
    :param frames: ``> 1`` 时做软件平均
    :param kind: ``"dark"`` 或 ``"bright"``
    """
    if kind not in ("dark", "bright"):
        raise InvalidParameterError(f"kind 只能是 'dark' 或 'bright'，收到 {kind!r}")
    count = int(frames)
    if count < 1:
        raise InvalidParameterError(f"frames 必须 >= 1，收到 {frames}")

    if count == 1:
        spectrum = device.measure(timeout_s=timeout_s)
    else:
        spectrum = average_frames(device, count, interval_s=interval_s, timeout_s=timeout_s)

    return Reference(
        kind=kind,
        spectrum=spectrum,
        conditions=ReferenceConditions.from_config(device.measurement_config),
        serial=device.info.serial,
        created=datetime.now(UTC),
        frames=count,
    )


def check_reference(
    reference: Reference,
    cfg: MeasurementConfig,
    *,
    serial: str | None = None,
    max_age_hours: float | None = DEFAULT_MAX_AGE_HOURS,
    now: datetime | None = None,
) -> ReferenceStatus:
    """判断参考谱是否还适用"""
    return reference.status(cfg, serial=serial, max_age_hours=max_age_hours, now=now)
