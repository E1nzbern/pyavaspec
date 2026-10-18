"""features 自动曝光的脱机测试：纯状态机 + FakeAccess 编排。"""

from __future__ import annotations

import pytest

from _fakes import FakeAccess
from pyavaspec.core.errors import InvalidParameterError
from pyavaspec.core.models import MeasurementConfig, Spectrum
from pyavaspec.features import auto_exposure, search_exposure


def test_linear_response_converges() -> None:
    result = search_exposure(
        lambda t: 1.0 * t,
        saturation_level=1000,
        target_fraction=0.7,
        initial_integration_ms=10.0,
    )
    assert result.converged is True
    assert result.integration_ms == pytest.approx(700.0)
    assert result.peak_fraction == pytest.approx(0.7)


def test_saturation_halves_integration_time() -> None:
    def probe(t: float) -> float:
        return 1000.0 if t > 100.0 else 10.0 * t

    result = search_exposure(
        probe,
        saturation_level=1000,
        target_fraction=0.7,
        initial_integration_ms=1000.0,
    )
    assert result.converged is True
    assert result.integration_ms == pytest.approx(62.5)
    assert result.peak_counts == pytest.approx(625.0)


def test_no_signal_expands_then_gives_up() -> None:
    result = search_exposure(
        lambda t: 0.0,
        saturation_level=1000,
        max_integration_ms=100.0,
        initial_integration_ms=1.0,
    )
    assert result.converged is False
    assert result.integration_ms == pytest.approx(100.0)


def test_gives_up_when_max_integration_still_under_exposed() -> None:
    result = search_exposure(
        lambda t: 1.0 * t,
        saturation_level=1000,
        min_integration_ms=1.0,
        max_integration_ms=10.0,
        initial_integration_ms=10.0,
    )
    assert result.converged is False
    assert result.integration_ms == pytest.approx(10.0)
    assert result.peak_counts == pytest.approx(10.0)


def test_rejects_invalid_parameters() -> None:
    with pytest.raises(InvalidParameterError):
        search_exposure(lambda t: 0.0, saturation_level=0)
    with pytest.raises(InvalidParameterError):
        search_exposure(lambda t: 0.0, saturation_level=1000, target_fraction=1.0)
    with pytest.raises(InvalidParameterError):
        search_exposure(lambda t: 0.0, saturation_level=1000, tolerance=0.0)


def test_auto_exposure_leaves_device_at_best_result() -> None:
    device = FakeAccess(integration_ms=10.0, counts_per_ms=1.0)
    result = auto_exposure(device)
    assert result.converged is True
    assert device.measurement_config.integration_ms == pytest.approx(result.integration_ms)
    assert device.measure_calls == len(result.history)


def test_auto_exposure_keeps_averages_untouched() -> None:
    device = FakeAccess(integration_ms=10.0, averages=3, counts_per_ms=1.0)
    result = auto_exposure(device)
    assert result.converged is True
    assert device.measurement_config.averages == 3


class _FailingAccess(FakeAccess):
    """从第 ``fail_after`` 次测量起抛异常，用于验证自动曝光的失败回滚。"""

    def __init__(self, *, fail_after: int, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._fail_after = fail_after
        self.failed_at: MeasurementConfig | None = None

    def measure(self, **kwargs: object) -> Spectrum:
        if self.measure_calls >= self._fail_after:
            self.failed_at = self._config
            raise RuntimeError("模拟采集失败")
        return super().measure(**kwargs)  # type: ignore[arg-type]


def test_auto_exposure_restores_config_when_measure_fails() -> None:
    device = _FailingAccess(fail_after=1, integration_ms=10.0, averages=3, counts_per_ms=1.0)

    with pytest.raises(RuntimeError):
        auto_exposure(device)

    # 失败时设备确实已经被调到探测中途的配置
    assert device.failed_at is not None
    assert device.failed_at.integration_ms > 1000.0

    # 回滚到调用前的积分时间，平均次数全程未被动过
    assert device.measurement_config.integration_ms == pytest.approx(10.0)
    assert device.measurement_config.averages == 3
