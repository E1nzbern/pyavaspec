"""校验光谱之间是否可进行计算

多帧平均、暗扣除、透射比、反射率等基于光谱数据的计算都要求参与运算的光谱来自同一测量参数。
"""

from __future__ import annotations

from ..core.errors import InvalidParameterError
from ..core.models import Spectrum

__all__ = ["INTEGRATION_TOLERANCE_MS", "require_compatible"]

#: 积分时间比较浮点容差（ms）
INTEGRATION_TOLERANCE_MS = 1e-9


def require_compatible(first: Spectrum, other: Spectrum) -> None:
    """校验两张谱可逐像素运算

    要求像素数、像素范围、积分时间、平均次数、满量程（ADC 位数）一致，
    不一致时抛 :class:`~pyavaspec.core.errors.InvalidParameterError`。
    """
    if first.counts.shape != other.counts.shape:
        raise InvalidParameterError(f"光谱像素数不一致：{first.counts.size} 与 {other.counts.size}")
    if (first.start_pixel, first.stop_pixel) != (
        other.start_pixel,
        other.stop_pixel,
    ):
        raise InvalidParameterError(
            "光谱像素范围不一致："
            f"({first.start_pixel}, {first.stop_pixel}) 与 "
            f"({other.start_pixel}, {other.stop_pixel})"
        )
    if abs(first.integration_ms - other.integration_ms) >= INTEGRATION_TOLERANCE_MS:
        raise InvalidParameterError(
            f"积分时间不一致：{first.integration_ms:g} 与 {other.integration_ms:g} ms"
        )
    if first.averages != other.averages:
        raise InvalidParameterError(f"平均次数不一致：{first.averages} 与 {other.averages}")
    if first.saturation_level != other.saturation_level:
        raise InvalidParameterError(
            f"满量程不一致：{first.saturation_level} 与 {other.saturation_level}"
        )
