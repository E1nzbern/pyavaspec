"""pyavaspec core 层公开 API

用法::

    from pyavaspec import Spectrometer

    with Spectrometer() as spec:
        spec.configure(integration_ms=100, averages=2)
        frame = spec.measure()

依赖 pyavaspec._lowlevel，被 pyavaspec.features 依赖
"""

from __future__ import annotations

from .._lowlevel._types import (
    DeviceStatus,
    Port,
    SensorType,
    SmoothingModel,
    TriggerMode,
    TriggerSource,
    TriggerSourceType,
)
from .device import (
    DriverSession,
    Spectrometer,
    SpectrumStream,
    list_devices,
    status_by_serial,
)
from .errors import (
    AvaError,
    AvsError,
    CommunicationError,
    DeviceBusyError,
    DeviceNotFoundError,
    DeviceNotOpenError,
    DeviceWriteError,
    DllAlreadyLoadedError,
    DllNotFoundError,
    IncompleteAcquisitionError,
    InvalidParameterError,
    InvalidStateError,
    MeasurementError,
    MeasurementInProgressError,
    MeasurementTimeoutError,
    OperationNotSupportedError,
    UnsupportedPlatformError,
)
from .io import DeviceIO
from .models import (
    DeviceConfig,
    DeviceIdentity,
    DeviceInfo,
    MeasurementConfig,
    Spectrum,
    Trigger,
)

__all__ = [
    "AvaError",
    "AvsError",
    "CommunicationError",
    "DeviceBusyError",
    "DeviceConfig",
    "DeviceIO",
    "DeviceIdentity",
    "DeviceInfo",
    "DeviceNotFoundError",
    "DeviceNotOpenError",
    "DeviceStatus",
    "DeviceWriteError",
    "DllAlreadyLoadedError",
    "DllNotFoundError",
    "DriverSession",
    "IncompleteAcquisitionError",
    "InvalidParameterError",
    "InvalidStateError",
    "MeasurementConfig",
    "MeasurementError",
    "MeasurementInProgressError",
    "MeasurementTimeoutError",
    "OperationNotSupportedError",
    "Port",
    "SensorType",
    "SmoothingModel",
    "Spectrometer",
    "Spectrum",
    "SpectrumStream",
    "Trigger",
    "TriggerMode",
    "TriggerSource",
    "TriggerSourceType",
    "UnsupportedPlatformError",
    "list_devices",
    "status_by_serial",
]
