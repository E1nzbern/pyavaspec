"""`avaspecx64.dll` 的 ctypes 封装

- `_binding` / `_binding.pyi`: `AVS_*` 函数原型
- `_loader` / `_session`: DLL 定位、平台加载器、``AVS_Init`` 引用计数会话
- `_structs` / `_constants` / `_types`: 结构体与枚举
- `_errors`: 返回码和异常
- `client.AvaSpecx`: DLL 的 Pythonic API

.. warning::
   这是内部实现层，接口可能随实现调整，不属于稳定公共 API
   上层应通过 :mod:`pyavaspec.core` / :mod:`pyavaspec.features` 调用
"""

from __future__ import annotations

from ._errors import (
    AvaError,
    AvsError,
    DeviceNotFoundError,
    DllAlreadyLoadedError,
    DllNotFoundError,
    UnsupportedPlatformError,
)
from ._loader import find_dll, load_library, register_loader
from .client import AvaSpecx, RawScopeData, ScopeData, VersionInfo

__all__ = [
    "AvaError",
    "AvaSpecx",
    "AvsError",
    "DeviceNotFoundError",
    "DllAlreadyLoadedError",
    "DllNotFoundError",
    "RawScopeData",
    "ScopeData",
    "UnsupportedPlatformError",
    "VersionInfo",
    "find_dll",
    "load_library",
    "register_loader",
]
