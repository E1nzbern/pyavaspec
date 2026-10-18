"""在 :mod:`pyavaspec.core` 之上提供仪器操作级别的高级 API"""

from __future__ import annotations

from .averaging import average_frames, mean_spectrum
from .diagnostics import (
    CheckResult,
    DeviceReport,
    SelfTestReport,
    device_report,
    digital_loopback,
    self_test,
)
from .exposure import (
    ExposureResult,
    ExposureStep,
    auto_exposure,
    search_exposure,
)
from .reference import (
    DEFAULT_MAX_AGE_HOURS,
    REFERENCE_FORMAT,
    Reference,
    ReferenceConditions,
    ReferenceInvalidError,
    ReferencePair,
    ReferenceStatus,
    capture_reference,
    check_reference,
)
from .session import Measurement, MeasurementSession, SessionStatus, StalePolicy
from .spectral import (
    MIN_REFERENCE_FRACTION,
    RelativeResult,
    dark_corrected,
    relative_reflectance,
    transmittance,
)

__all__ = [
    "DEFAULT_MAX_AGE_HOURS",
    "MIN_REFERENCE_FRACTION",
    "REFERENCE_FORMAT",
    "CheckResult",
    "DeviceReport",
    "ExposureResult",
    "ExposureStep",
    "Measurement",
    "MeasurementSession",
    "Reference",
    "ReferenceConditions",
    "ReferenceInvalidError",
    "ReferencePair",
    "ReferenceStatus",
    "RelativeResult",
    "SelfTestReport",
    "SessionStatus",
    "StalePolicy",
    "auto_exposure",
    "average_frames",
    "capture_reference",
    "check_reference",
    "dark_corrected",
    "device_report",
    "digital_loopback",
    "mean_spectrum",
    "relative_reflectance",
    "search_exposure",
    "self_test",
    "transmittance",
]
