"""自动积分时间"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..core.errors import InvalidParameterError

if TYPE_CHECKING:
    from ._device import DeviceAccess

__all__ = [
    "ExposureResult",
    "ExposureStep",
    "auto_exposure",
    "search_exposure",
]

#: 峰值达到满量程该比例即视为饱和
SATURATED_FRACTION = 0.95
#: ``t_next`` 变化小于该值即认为积分时间已到边界
_MIN_STEP_MS = 1e-6


@dataclass(frozen=True, slots=True)
class ExposureStep:
    """一次探测的输入和结果"""

    integration_ms: float
    peak_counts: float


@dataclass(frozen=True, slots=True)
class ExposureResult:
    """自动曝光结果，包含过程记录"""

    integration_ms: float
    peak_counts: float
    saturation_level: int
    converged: bool
    history: tuple[ExposureStep, ...]

    @property
    def peak_fraction(self) -> float:
        """峰值占满量程的比例"""
        if self.saturation_level <= 0:
            return 0.0
        return self.peak_counts / self.saturation_level

    def as_dict(self) -> dict[str, Any]:
        return {
            "integration_ms": self.integration_ms,
            "peak_counts": self.peak_counts,
            "saturation_level": self.saturation_level,
            "peak_fraction": round(self.peak_fraction, 4),
            "converged": self.converged,
            "iterations": len(self.history),
        }


def _closer(current: ExposureStep | None, candidate: ExposureStep, goal: float):
    if current is None:
        return candidate
    return (
        candidate
        if abs(candidate.peak_counts - goal) <= abs(current.peak_counts - goal)
        else current
    )


def search_exposure(
    probe: Callable[[float], float],
    *,
    saturation_level: int,
    target_fraction: float = 0.7,
    tolerance: float = 0.15,
    min_integration_ms: float = 0.5,
    max_integration_ms: float = 60000.0,
    max_iterations: int = 10,
    initial_integration_ms: float = 10.0,
) -> ExposureResult:
    """搜索使峰值落在 ``target_fraction ~ tolerance`` 的积分时间

    :param probe: ``integration_ms -> peak_counts``，由调用方负责真正测量

    :return: 达到迭代上限仍未收敛时，返回离目标最近的一次结果并注明未收敛
    """
    level = int(saturation_level)
    if level <= 0:
        raise InvalidParameterError(f"saturation_level 必须为正，收到 {saturation_level}")
    if not (0.0 < target_fraction < 1.0):
        raise InvalidParameterError(f"target_fraction 需在 (0, 1)，收到 {target_fraction}")
    if tolerance <= 0.0:
        raise InvalidParameterError(f"tolerance 需为正，收到 {tolerance}")
    if not (0.0 < min_integration_ms <= max_integration_ms):
        raise InvalidParameterError(
            f"积分时间范围非法：({min_integration_ms}, {max_integration_ms})"
        )
    if max_iterations < 1:
        raise InvalidParameterError(f"max_iterations 必须 >= 1，收到 {max_iterations}")

    saturation = float(level)
    goal = target_fraction * saturation
    lower = max(goal - tolerance * saturation, 0.0)
    upper = min(goal + tolerance * saturation, SATURATED_FRACTION * saturation)

    t = min(max(float(initial_integration_ms), min_integration_ms), max_integration_ms)

    history: list[ExposureStep] = []
    best: ExposureStep | None = None

    for _ in range(int(max_iterations)):
        peak = float(probe(t))
        step = ExposureStep(integration_ms=t, peak_counts=peak)
        history.append(step)
        best = _closer(best, step, goal)

        if peak >= SATURATED_FRACTION * saturation:
            if t <= min_integration_ms:
                break
            t = max(min_integration_ms, t * 0.5)
            continue

        if lower <= peak <= upper:
            return ExposureResult(t, peak, level, True, tuple(history))

        if peak <= 0.0:
            if t >= max_integration_ms:
                break
            t = min(max_integration_ms, t * 10.0)
            continue

        t_next = min(
            max_integration_ms,
            max(min_integration_ms, t * goal / peak),
        )
        if abs(t_next - t) < _MIN_STEP_MS:
            break
        t = t_next

    assert best is not None
    return ExposureResult(
        best.integration_ms,
        best.peak_counts,
        level,
        False,
        tuple(history),
    )


def auto_exposure(
    device: DeviceAccess,
    *,
    target_fraction: float = 0.7,
    tolerance: float = 0.15,
    min_integration_ms: float = 0.5,
    max_integration_ms: float = 60000.0,
    max_iterations: int = 10,
    timeout_s: float | None = None,
) -> ExposureResult:
    """在设备上执行自动曝光，结束时把积分时间配置到最佳结果，失败时回滚

    平均次数不参与搜索，全程保持调用前的值不变。
    """
    cfg = device.measurement_config
    original_integration = cfg.integration_ms

    def probe(integration_ms: float) -> float:
        device.configure(integration_ms=integration_ms)
        return float(device.measure(timeout_s=timeout_s).max)

    try:
        result = search_exposure(
            probe,
            saturation_level=cfg.saturation_level,
            target_fraction=target_fraction,
            tolerance=tolerance,
            min_integration_ms=min_integration_ms,
            max_integration_ms=max_integration_ms,
            max_iterations=max_iterations,
            initial_integration_ms=original_integration,
        )
        device.configure(integration_ms=result.integration_ms)
    except BaseException:
        # 回滚失败时保留原始异常
        with contextlib.suppress(Exception):
            device.configure(integration_ms=original_integration)
        raise
    return result
