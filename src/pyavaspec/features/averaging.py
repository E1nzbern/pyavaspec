"""多帧平均、相加，用于降噪"""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

import numpy as np

from ..core.errors import InvalidParameterError
from ..core.models import Spectrum
from ._conditions import require_compatible

if TYPE_CHECKING:
    from ._device import DeviceAccess

__all__ = ["average_frames", "mean_spectrum"]


def mean_spectrum(spectra: Sequence[Spectrum] | Iterable[Spectrum]) -> Spectrum:
    """对多帧同参数光谱做逐像素平均，返回新的 :class:`Spectrum`

    - ``counts`` 取算术平均
    - 所有帧都有 ``saturated_mask`` 时，任一帧饱和就标记该像素为饱和
    - 所有帧都有 ``raw_counts`` 时取算术平均
    - 其余元信息沿用第一帧

    帧数不足、采集条件或像素范围不一致时抛
    :class:`~pyavaspec.core.errors.InvalidParameterError`。
    """
    frames = list(spectra)
    if not frames:
        raise InvalidParameterError("mean_spectrum 至少需要一帧")
    first = frames[0]
    for frame in frames[1:]:
        require_compatible(first, frame)

    counts = np.mean([frame.counts for frame in frames], axis=0)

    masks = [frame.saturated_mask for frame in frames]
    saturated_mask = (
        np.logical_or.reduce([np.asarray(m, dtype=bool) for m in masks])
        if all(m is not None for m in masks)
        else None
    )

    raws = [frame.raw_counts for frame in frames]
    raw_counts = (
        np.mean([np.asarray(r, dtype=np.float64) for r in raws], axis=0)
        if all(r is not None for r in raws)
        else None
    )

    return Spectrum(
        wavelengths=first.wavelengths,
        counts=np.asarray(counts, dtype=np.float64),
        timestamp_ticks=first.timestamp_ticks,
        integration_ms=first.integration_ms,
        averages=first.averages,
        start_pixel=first.start_pixel,
        stop_pixel=first.stop_pixel,
        saturation_level=first.saturation_level,
        sequence=first.sequence,
        host_time=first.host_time,
        saturated_mask=saturated_mask,
        raw_counts=raw_counts,
        raw_averages=first.raw_averages,
    )


def average_frames(
    device: DeviceAccess,
    frames: int,
    *,
    interval_s: float = 0.0,
    timeout_s: float | None = None,
    raw: bool = False,
    saturated_mask: bool = False,
) -> Spectrum:
    """
    在设备上连续采集 ``frames`` 帧并做软件平均

    :param interval_s: 帧间等待秒数
    """
    count = int(frames)
    if count < 1:
        raise InvalidParameterError(f"frames 必须 >= 1，收到 {frames}")
    collected: list[Spectrum] = []
    for i in range(count):
        if interval_s > 0 and i > 0:
            time.sleep(float(interval_s))
        collected.append(
            device.measure(timeout_s=timeout_s, raw=raw, saturated_mask=saturated_mask)
        )
    return mean_spectrum(collected)
