"""``DriverAdapter`` / ``BoundDevice`` 测试：返回码翻译唯一 seam 与句柄绑定。"""

from __future__ import annotations

import pytest

from _fakes import FakeNativeClient
from pyavaspec._lowlevel._errors import AvsError
from pyavaspec.core._driver import DriverAdapter
from pyavaspec.core.errors import _CODE_MAP, InvalidStateError, MeasurementError

# %% 返回码翻译（唯一 seam）


@pytest.mark.parametrize("code,expected", list(_CODE_MAP.items()))
def test_adapter_translates_every_mapped_code(code: object, expected: type) -> None:
    client = FakeNativeClient(
        get_num_pixels=AvsError("AVS_GetNumPixels", int(code))  # type: ignore[arg-type]
    )
    adapter = DriverAdapter(client)  # type: ignore[arg-type]
    with pytest.raises(expected) as excinfo:
        adapter.read_num_pixels(1)
    assert getattr(excinfo.value, "code", None) == int(code)  # type: ignore[arg-type]


def test_adapter_passes_through_unknown_code() -> None:
    client = FakeNativeClient(get_num_pixels=AvsError("AVS_GetNumPixels", -9999))
    adapter = DriverAdapter(client)  # type: ignore[arg-type]
    with pytest.raises(AvsError) as excinfo:
        adapter.read_num_pixels(1)
    assert excinfo.value.code == -9999


def test_adapter_translates_acquisition_primitive() -> None:
    client = FakeNativeClient(get_scope_data=AvsError("AVS_GetScopeData", -17))
    adapter = DriverAdapter(client)  # type: ignore[arg-type]
    with pytest.raises(MeasurementError) as excinfo:
        adapter.read_frame(1, 4)
    assert getattr(excinfo.value, "code", None) == -17


def test_adapter_does_not_touch_usb_list_when_devices_present() -> None:
    calls: list[str] = []

    class Client(FakeNativeClient):
        def update_usb_devices(self) -> int:
            calls.append("update")
            return 1

        def get_list(self, count: int | None = None) -> list[object]:
            calls.append("list")
            return [object()]

    adapter = DriverAdapter(Client())  # type: ignore[arg-type]
    assert len(adapter.list_devices()) == 1
    assert calls == ["list"]


def test_adapter_refreshes_only_when_list_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pyavaspec.core._driver._EMPTY_RETRY_S", 0)
    calls: list[str] = []
    responses: list[list[object]] = [[], [object()]]

    class Client(FakeNativeClient):
        def update_usb_devices(self) -> int:
            calls.append("update")
            return 1

        def get_list(self, count: int | None = None) -> list[object]:
            calls.append("list")
            return responses.pop(0) if responses else []

    adapter = DriverAdapter(Client())  # type: ignore[arg-type]
    assert len(adapter.list_devices()) == 1
    assert calls == ["list", "update", "list"]


# %% BoundDevice：句柄绑定 + 存活守卫


def test_bound_device_hides_handle_and_calls_guard() -> None:
    seen: list[int] = []

    def guard() -> None:
        seen.append(1)

    adapter = DriverAdapter(FakeNativeClient(get_num_pixels=4))  # type: ignore[arg-type]
    device = adapter.bind(7, guard)
    assert device.read_num_pixels() == 4
    assert seen == [1]


def test_bound_device_guard_error_propagates() -> None:
    def guard() -> None:
        raise InvalidStateError("底层会话已被关闭")

    adapter = DriverAdapter(FakeNativeClient(get_num_pixels=4))  # type: ignore[arg-type]
    device = adapter.bind(1, guard)
    with pytest.raises(InvalidStateError):
        device.read_num_pixels()


def test_bound_device_deactivate_is_idempotent_and_invalidates() -> None:
    adapter = DriverAdapter(FakeNativeClient(get_num_pixels=4))  # type: ignore[arg-type]
    device = adapter.bind(1, lambda: None)
    device.deactivate()
    device.deactivate()  # 幂等
    with pytest.raises(InvalidStateError):
        device.read_num_pixels()
