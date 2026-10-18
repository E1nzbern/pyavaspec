"""``DriverSession`` 门面测试：会话复用、驱动注入与状态校验（不需要硬件）。

用假 ``AvaSpecx`` 替换 ``core.device`` 里的低层入口，验证 ``DriverSession`` 自身
构造 :class:`~pyavaspec.core._driver.DriverAdapter` 的生命周期编排与查询委托；
其余用例通过 ``driver=`` 注入替换驱动适配器。
"""

from __future__ import annotations

from typing import ClassVar, Self

import pytest

from _fakes import FakeDriver
from pyavaspec._lowlevel._structs import AvsIdentityType
from pyavaspec._lowlevel._types import DeviceStatus
from pyavaspec.core import (
    DriverSession,
    InvalidStateError,
    Port,
    list_devices,
    status_by_serial,
)
from pyavaspec.core import device as device_module


class FakeAvaSpecx:
    """替代低层 ``AvaSpecx`` 的会话替身，记录生命周期与查询调用。

    只实现 ``DriverAdapter`` 会用到的会话方法——协议是结构化的，无需补齐全部桩。
    """

    instances: ClassVar[list[FakeAvaSpecx]] = []

    def __init__(self, dll_path: str | None = None, *, port: int = 0) -> None:
        self.dll_path = dll_path
        self.port = port
        self.opened = False
        self.closed = False
        self.list_calls = 0
        self.status_calls: list[str] = []
        self.instances.append(self)

    def open(self) -> Self:
        self.opened = True
        return self

    def close(self) -> None:
        self.closed = True

    def get_list(self, count: int | None = None) -> list[AvsIdentityType]:
        self.list_calls += 1
        ident = AvsIdentityType()
        ident.SerialNumber = b"FAKE0001"
        ident.UserFriendlyName = b"fake"
        ident.Status = 1
        return [ident]

    def get_status_by_serial(self, serial: str) -> int:
        self.status_calls.append(serial)
        return 1


@pytest.fixture(autouse=True)
def patch_avaspecx(monkeypatch: pytest.MonkeyPatch) -> type[FakeAvaSpecx]:
    FakeAvaSpecx.instances = []
    monkeypatch.setattr(device_module, "AvaSpecx", FakeAvaSpecx)
    return FakeAvaSpecx


# %% 生命周期


def test_session_reuses_one_lowlevel_session(
    patch_avaspecx: type[FakeAvaSpecx],
) -> None:
    with DriverSession() as session:
        first = session.list_devices()
        second = session.list_devices()

    assert len(patch_avaspecx.instances) == 1  # 只构造了一个低层会话
    client = patch_avaspecx.instances[0]
    assert client.list_calls == 2
    assert client.opened is True
    assert client.closed is True
    assert first[0].serial == "FAKE0001"
    assert second[0].serial == "FAKE0001"


def test_close_is_idempotent(patch_avaspecx: type[FakeAvaSpecx]) -> None:
    session = DriverSession().open()
    session.close()
    session.close()
    assert patch_avaspecx.instances[0].closed is True
    assert session.is_open is False


def test_open_failure_does_not_cache_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Boom(FakeAvaSpecx):
        def open(self) -> Self:
            raise RuntimeError("boom")

    monkeypatch.setattr(device_module, "AvaSpecx", Boom)
    session = DriverSession()
    with pytest.raises(RuntimeError):
        session.open()
    assert session.is_open is False
    assert session._driver is None  # 失败后回滚，允许重试


# %% 便捷函数委托


def test_convenience_functions_reuse_given_session(
    patch_avaspecx: type[FakeAvaSpecx],
) -> None:
    with DriverSession() as session:
        devices = list_devices(session=session)
        status = status_by_serial("FAKE0001", session=session)

    assert len(patch_avaspecx.instances) == 1  # 没有额外开窗
    assert devices[0].serial == "FAKE0001"
    assert status is DeviceStatus.USB_AVAILABLE
    assert patch_avaspecx.instances[0].status_calls == ["FAKE0001"]


def test_transient_session_is_closed(patch_avaspecx: type[FakeAvaSpecx]) -> None:
    list_devices()
    assert len(patch_avaspecx.instances) == 1
    assert patch_avaspecx.instances[0].opened is True
    assert patch_avaspecx.instances[0].closed is True


def test_positional_dll_path_is_still_supported(
    patch_avaspecx: type[FakeAvaSpecx],
) -> None:
    list_devices("C:/fake/avaspecx64.dll")
    status_by_serial("FAKE0001", "C:/fake/avaspecx64.dll")
    assert [c.dll_path for c in patch_avaspecx.instances] == [
        "C:/fake/avaspecx64.dll",
        "C:/fake/avaspecx64.dll",
    ]


def test_port_is_forwarded_to_transient_session(
    patch_avaspecx: type[FakeAvaSpecx],
) -> None:
    list_devices(port=Port.ETH)
    status_by_serial("FAKE0001", port=Port.ETH)
    assert [c.port for c in patch_avaspecx.instances] == [
        int(Port.ETH),
        int(Port.ETH),
    ]


# %% 驱动注入与状态校验


def test_injected_driver_can_be_reopened() -> None:
    driver = FakeDriver()
    session = DriverSession(driver=driver)  # type: ignore[arg-type]
    with session:
        assert session.list_devices()[0].serial == "FAKE0001"
    assert driver.closed is True
    with session:  # 复用注入的驱动重新打开，不新建低层
        assert session.get_status_by_serial("FAKE0001") is DeviceStatus.USB_AVAILABLE
    assert FakeAvaSpecx.instances == []


def test_driver_conflicts_with_dll_path() -> None:
    with pytest.raises(ValueError):
        DriverSession("C:/fake/avaspecx64.dll", driver=FakeDriver())  # type: ignore[arg-type]


def test_operations_require_open() -> None:
    session = DriverSession()
    assert session.is_open is False
    with pytest.raises(InvalidStateError):
        session.list_devices()
    with pytest.raises(InvalidStateError):
        session.get_status_by_serial("FAKE0001")
