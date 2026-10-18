"""features 多帧平均的脱机测试。"""

from __future__ import annotations

import numpy as np
import pytest

from _fakes import FakeAccess
from pyavaspec.core.errors import InvalidParameterError
from pyavaspec.core.models import Spectrum
from pyavaspec.features import average_frames, mean_spectrum


def _spectrum(counts: object, **overrides: object) -> Spectrum:
    array = np.asarray(counts, dtype=np.float64)
    size = array.size
    values: dict[str, object] = {
        "wavelengths": np.linspace(400.0, 700.0, size),
        "counts": array,
        "timestamp_ticks": 1,
        "integration_ms": 5.0,
        "averages": 1,
        "start_pixel": 0,
        "stop_pixel": size - 1,
        "saturation_level": 65535,
    }
    values.update(overrides)
    return Spectrum(**values)  # type: ignore[arg-type]


def test_mean_spectrum_averages_counts() -> None:
    merged = mean_spectrum([_spectrum([0.0, 10.0]), _spectrum([10.0, 20.0])])
    assert merged.counts == pytest.approx([5.0, 15.0])
    assert merged.timestamp_ticks == 1
    assert merged.integration_ms == pytest.approx(5.0)


def test_mean_spectrum_ors_saturation_masks() -> None:
    first = _spectrum([1.0, 2.0], saturated_mask=np.array([True, False]))
    second = _spectrum([3.0, 4.0], saturated_mask=np.array([False, False]))
    merged = mean_spectrum([first, second])
    assert merged.saturated_mask is not None
    assert list(merged.saturated_mask) == [True, False]


def test_mean_spectrum_drops_mask_when_missing() -> None:
    first = _spectrum([1.0, 2.0], saturated_mask=np.array([True, False]))
    merged = mean_spectrum([first, _spectrum([3.0, 4.0])])
    assert merged.saturated_mask is None


def test_mean_spectrum_averages_raw_counts() -> None:
    first = _spectrum([1.0, 1.0], raw_counts=np.array([10.0, 20.0]))
    second = _spectrum([1.0, 1.0], raw_counts=np.array([30.0, 40.0]))
    merged = mean_spectrum([first, second])
    assert merged.raw_counts == pytest.approx([20.0, 30.0])


def test_mean_spectrum_rejects_empty() -> None:
    with pytest.raises(InvalidParameterError):
        mean_spectrum([])


def test_mean_spectrum_rejects_mismatched_shape() -> None:
    with pytest.raises(InvalidParameterError):
        mean_spectrum([_spectrum([1.0, 2.0]), _spectrum([1.0, 2.0, 3.0])])


def test_mean_spectrum_rejects_mismatched_pixel_range() -> None:
    with pytest.raises(InvalidParameterError):
        mean_spectrum([_spectrum([1.0, 2.0]), _spectrum([1.0, 2.0], start_pixel=1, stop_pixel=2)])


@pytest.mark.parametrize(
    "overrides",
    [
        {"integration_ms": 50.0},
        {"averages": 4},
        {"saturation_level": 16383},
    ],
)
def test_mean_spectrum_rejects_mismatched_acquisition_conditions(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(InvalidParameterError):
        mean_spectrum([_spectrum([1.0, 2.0]), _spectrum([3.0, 4.0], **overrides)])


def test_average_frames_measures_requested_count() -> None:
    device = FakeAccess(counts_per_ms=1.0)
    merged = average_frames(device, 3)
    assert device.measure_calls == 3
    assert merged.size == 4


def test_average_frames_rejects_non_positive() -> None:
    device = FakeAccess()
    with pytest.raises(InvalidParameterError):
        average_frames(device, 0)
