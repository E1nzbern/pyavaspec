"""引用计数

`AVS_Init` / `AVS_Done` 是进程级全局状态

仅供 :mod:`pyavaspec._lowlevel.client` 使用
"""

from __future__ import annotations

import atexit
import contextlib
import os
import sys
import threading
import traceback
from collections.abc import Callable
from typing import Protocol, TypeVar

from ._binding import _AvaSpecxNative
from ._errors import AvsError, DeviceNotFoundError, DllAlreadyLoadedError
from ._loader import _resolve, _resolve_loader, find_dll
from ._types import Port

__all__ = ["Lease", "acquire", "library", "stats"]


class DllLike(Protocol):
    """最小接口，方便测试。"""

    path: str

    def _Init(self, port: int, /) -> int: ...
    def _Done(self) -> int: ...


DllT = TypeVar("DllT", bound=DllLike)


class Lease[DllT: DllLike]:
    """一次会话的租约"""

    def __init__(
        self,
        dll: DllT,
        release: Callable[[], None],
        origin: str,
    ) -> None:
        self.dll = dll
        self.origin = origin
        self._release: Callable[[], None] | None = release

    def close(self) -> None:
        release, self._release = self._release, None  # 先取空：保证幂等
        if release is not None:
            release()

    def __repr__(self) -> str:
        state = "已归还" if self._release is None else "持有中"
        return f"<Lease {state} 来自 {self.origin}>"


class _Session[DllT: DllLike]:
    """维护唯一的 DLL 和 `AVS_Init` 计数"""

    def __init__(self, factory: Callable[[str | None], DllT]) -> None:
        self._factory = factory
        self._lock = threading.Lock()
        self._dll: DllT | None = None
        self._users = 0

    def _library_locked(self, path: str | None) -> DllT:
        if self._dll is None:
            self._dll = self._factory(path)
        elif path is not None:
            # 已加载后只允许复用，不允许更换 DLL
            requested = _resolve(path)
            if os.path.normcase(requested) != os.path.normcase(self._dll.path):
                raise DllAlreadyLoadedError(
                    f"本进程已加载 {self._dll.path}，不能再加载 {requested}"
                )
        return self._dll

    def library(self, path: str | None = None) -> DllT:
        """加载并缓存唯一的 DLL"""
        with self._lock:
            return self._library_locked(path)

    def acquire(
        self,
        path: str | None = None,
        port: int = Port.USB,
        *,
        origin: str | None = None,
    ) -> Lease[DllT]:
        with self._lock:
            dll = self._library_locked(path)
            if self._users == 0:
                n = dll._Init(int(port))
                if n == 0:
                    # Init 成功但没有设备
                    with contextlib.suppress(Exception):
                        dll._Done()
                    raise DeviceNotFoundError(
                        "未发现设备。设备是否正在被其他软件（AvaSoft 8 / AvaSoftX）或进程占用？"
                    )
                if n < 0:
                    raise AvsError("AVS_Init", n)
            self._users += 1
            return Lease(dll, self._release, origin or _caller())

    def _release(self) -> None:
        with self._lock:
            self._users -= 1
            if self._users == 0 and self._dll is not None:
                self._dll._Done()

    def stats(self) -> dict:
        with self._lock:
            return {
                "loaded": self._dll is not None,
                "path": self._dll.path if self._dll is not None else None,
                "users": self._users,
            }


def _caller() -> str:
    """租约来源"""
    for frame in reversed(traceback.extract_stack(limit=8)[:-2]):
        if not frame.filename.endswith("_session.py"):
            return f"{os.path.basename(frame.filename)}:{frame.lineno} {frame.name}()"
    return "unknown"


def _load(path: str | None) -> _AvaSpecxNative:
    loader = _resolve_loader()  # 未注册平台报平台错误
    return _AvaSpecxNative(find_dll(path), loader=loader)


# 进程级唯一会话
_state: _Session[_AvaSpecxNative] = _Session(_load)


def library(path: str | None = None) -> _AvaSpecxNative:
    return _state.library(path)


def acquire(
    path: str | None = None,
    port: int = Port.USB,
    *,
    origin: str | None = None,
) -> Lease[_AvaSpecxNative]:
    return _state.acquire(path, port, origin=origin)


def stats() -> dict:
    return _state.stats()


@atexit.register
def _warn_on_leak() -> None:
    leaked = _state.stats()["users"]
    if not leaked:
        return
    print(
        f"[avaspecx] 退出时仍有 {leaked} 个未归还的会话；请使用 `with AvaSpecx() as ava:`",
        file=sys.stderr,
    )
    with _state._lock:
        if _state._users and _state._dll is not None:
            with contextlib.suppress(Exception):
                _state._dll._Done()
        _state._users = 0
