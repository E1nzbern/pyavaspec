"""光谱计算模块，包括背景扣除、透射比、相对反射率、吸光度

接口只收**裸谱**
（:class:`~pyavaspec.core.models.Spectrum`）：参考谱的种类 / 设备 / 条件校验属于
:class:`~.reference.ReferencePair`，生命周期属于 :class:`~.session.MeasurementSession`，
本 module 只负责算术。参与运算的谱必须来自同一测量参数，由 :mod:`._conditions` 校验。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

import numpy as np

from ..core.errors import InvalidParameterError
from ..core.models import Spectrum
from ._conditions import require_compatible

__all__ = [
    "MIN_REFERENCE_FRACTION",
    "RelativeResult",
    "dark_corrected",
    "relative_reflectance",
    "transmittance",
]

#: ``(R - D)`` 低于满量程该比例的像素判为无效
MIN_REFERENCE_FRACTION = 0.01

Quantity = Literal["transmittance", "reflectance", "absorbance"]


@dataclass(frozen=True, slots=True)
class RelativeResult:
    """相对量计算结果

    透射比、反射率、吸光度

    - ``valid`` 为 ``False`` 的像素代表分母过小或数值非法，其 ``values`` 为 ``NaN``
    """

    source: Spectrum
    values: np.ndarray
    valid: np.ndarray
    quantity: Quantity

    def __post_init__(self) -> None:
        values = np.asarray(self.values, dtype=np.float64)
        valid = np.asarray(self.valid, dtype=bool)
        if values.shape != valid.shape:
            raise InvalidParameterError(
                f"values 和 valid 长度不一致：{values.size} 与 {valid.size}"
            )
        if values.size != self.source.counts.size:
            raise InvalidParameterError(
                f"结果长度 {values.size} 和源光谱 {self.source.counts.size} 不一致"
            )
        if values.flags.writeable:
            values.flags.writeable = False
        if valid.flags.writeable:
            valid.flags.writeable = False
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "valid", valid)

    @property
    def wavelengths(self) -> np.ndarray:
        """波长 nm，来自源光谱"""
        return self.source.wavelengths

    @property
    def size(self) -> int:
        return int(self.values.size)

    def absorbance(self) -> RelativeResult:
        """由透射比或反射率计算吸光度 ``-log10(values)``"""
        if self.quantity == "absorbance":
            return self
        with np.errstate(divide="ignore", invalid="ignore"):
            values = -np.log10(self.values)
        valid = self.valid & (self.values > 0.0) & np.isfinite(values)
        return replace(
            self,
            values=np.where(valid, values, np.nan),
            valid=valid,
            quantity="absorbance",
        )

    def to_spectrum(self) -> Spectrum:
        """转换为 :class:`Spectrum`"""
        return replace(
            self.source,
            counts=np.array(self.values, dtype=np.float64, copy=True),
        )


def dark_corrected(
    sample: Spectrum,
    dark: Spectrum,
    *,
    floor: float | None = 0.0,
) -> Spectrum:
    """
    背景扣除 ``S - D``

    :param floor: ``None`` 时不截断，否则将负值设置为 ``floor``
    """
    require_compatible(sample, dark)
    counts = np.asarray(sample.counts - dark.counts, dtype=np.float64)
    if floor is not None:
        counts = np.maximum(counts, float(floor))
    return replace(sample, counts=counts)


def transmittance(
    sample: Spectrum,
    dark: Spectrum,
    reference: Spectrum,
    *,
    min_reference_fraction: float = MIN_REFERENCE_FRACTION,
) -> RelativeResult:
    """
    透射比 ``(S - D) / (R - D)``

    上层调用请使用 ``ReferencePair.transmittance``

    ``(R - D)`` 小于满量程 ``min_reference_fraction`` 的像素判定为无效，置为 ``NaN``
    """
    require_compatible(sample, dark)
    require_compatible(sample, reference)

    numerator = np.asarray(sample.counts - dark.counts, dtype=np.float64)
    denominator = np.asarray(reference.counts - dark.counts, dtype=np.float64)
    threshold = float(min_reference_fraction) * sample.saturation_level
    valid = denominator > threshold
    with np.errstate(divide="ignore", invalid="ignore"):
        values = np.where(valid, numerator / denominator, np.nan)
    return RelativeResult(
        source=sample,
        values=values,
        valid=valid,
        quantity="transmittance",
    )


def relative_reflectance(
    sample: Spectrum,
    dark: Spectrum,
    reference: Spectrum,
    *,
    min_reference_fraction: float = MIN_REFERENCE_FRACTION,
) -> RelativeResult:
    """相对反射率，与透射比计算逻辑相同，仅 ``quantity`` 不同"""
    result = transmittance(sample, dark, reference, min_reference_fraction=min_reference_fraction)
    return replace(result, quantity="reflectance")
