"""DLL 定位和加载

目前只提供 Windows 平台的支持，支持路径参数传入、`AVASPEC_DLL` 环境变量、注册表方式查找支持的 DLL
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import sys
from collections.abc import Callable
from typing import Any

from ._errors import DllNotFoundError, UnsupportedPlatformError

__all__ = [
    "dll_candidates",
    "find_dll",
    "iter_install_path",
    "load_library",
    "register_loader",
]

# 可直接给 DLL 文件，也可给安装目录
_ENV_DLL = "AVASPEC_DLL"
_DLL_NAME = "avaspecx64.dll" if ctypes.sizeof(ctypes.c_voidp) == 8 else "avaspec.dll"
_REGISTRY_KEYWORD = "AvaSoftX"

if sys.platform.startswith("win"):
    import winreg
else:  # 使非 Windows 平台也可以正常 import
    winreg = None


# %% 平台加载器


# 平台前缀 → 加载器
_LOADERS: dict[str, Callable[[str], Any]] = {}


def register_loader(prefix: str, loader: Callable[[str], Any]) -> None:
    """
    注册平台加载器

    例如 `register_loader("linux", ctypes.CDLL)`

    只保证能加载，非 Windows 未经验证
    """
    _LOADERS[prefix] = loader


def _resolve_loader() -> Callable[[str], Any]:
    for prefix, loader in _LOADERS.items():
        if sys.platform.startswith(prefix):
            return loader
    raise UnsupportedPlatformError(
        f"平台 {sys.platform!r} 没有可用的 avaspecx 加载器；"
        f"当前只支持 Windows 平台，已注册前缀 {sorted(_LOADERS)}。"
        "移植请用 avaspecx.register_loader() 注册并自行验证调用约定。"
    )


def load_library(path: str) -> Any:
    """
    唯一的动态库加载入口

    未注册平台抛出异常 `UnsupportedPlatformError`
    """
    return _resolve_loader()(path)


# 必须持有 `add_dll_directory` 的句柄，否则目录注册会被撤销
_DLL_DIR_HANDLES: list[object] = []
_DLL_DIR_SEEN: set[str] = set()


def _load_windows(path: str) -> Any:
    """
    Windows 平台加载

    把 DLL 所在目录加入常驻搜索路径后加载
    """
    directory = os.path.dirname(path)
    add = getattr(os, "add_dll_directory", None)
    if add is not None and directory and directory not in _DLL_DIR_SEEN:
        _DLL_DIR_SEEN.add(directory)
        with contextlib.suppress(OSError):  # 目录无效时通过 WinDLL 报错
            _DLL_DIR_HANDLES.append(add(directory))
    return ctypes.WinDLL(path)  # type: ignore[attr-defined, unused-ignore]


_LOADERS["win32"] = _load_windows


# %% 注册表来源


def iter_install_path(target_name: str):
    """
    通过软件名称关键字匹配注册表卸载信息，输出软件安装路径

    :param target_name: 软件名称关键字，不区分大小写，如 `AvaSoftX`
    :return: 匹配到的软件信息字典迭代器，包含 `DisplayName`, `DisplayVersion`, `InstallLocation`
    """
    if winreg is None:
        return

    # 注册表根键和路径
    root_keys = [
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        ),
        (
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        ),
    ]

    # 扫描的架构
    views = [
        winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
    ]

    target_lower = target_name.lower()
    seen_locations = set()

    for root_key, subkey_path in root_keys:
        for access_mask in views:
            try:
                with winreg.OpenKey(root_key, subkey_path, 0, access_mask) as key:
                    num_subkeys = winreg.QueryInfoKey(key)[0]

                    for i in range(num_subkeys):
                        try:
                            sub_name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, sub_name, 0, access_mask) as sub_key:
                                # 匹配软件名
                                display_name = _query_value(sub_key, "DisplayName")
                                if not display_name:
                                    continue
                                if (target_lower not in display_name.lower()) or (
                                    target_lower not in sub_name.lower()
                                ):
                                    continue

                                # 命中后读取信息
                                install_loc = _query_value(sub_key, "InstallLocation")

                                final_path = install_loc
                                if not final_path:
                                    uninstall_str = _query_value(sub_key, "UninstallString")
                                    if uninstall_str:
                                        clean_path = uninstall_str.strip('"').split(",")[0]
                                        if os.path.exists(clean_path):
                                            final_path = os.path.dirname(clean_path)

                                # 去重
                                unique_key = (display_name, final_path)
                                if unique_key in seen_locations:
                                    continue
                                seen_locations.add(unique_key)

                                yield {
                                    "DisplayName": display_name,
                                    "DisplayVersion": _query_value(sub_key, "DisplayVersion") or "",
                                    "InstallLocation": final_path or "",
                                    "RegistrySubKey": sub_name,
                                }
                        except (PermissionError, FileNotFoundError, OSError):
                            continue
            except (PermissionError, FileNotFoundError, OSError):
                continue


def _query_value(key, name: str) -> str | None:
    if winreg is None:
        return None
    try:
        val, _ = winreg.QueryValueEx(key, name)
        return str(val).strip()
    except OSError:
        return None


def _registry_dirs() -> list[str]:
    """注册表里的 Avantes 安装目录，非 Windows 返回空列表"""
    if winreg is None:
        return []
    return [
        row["InstallLocation"]
        for row in iter_install_path(_REGISTRY_KEYWORD)
        if row["InstallLocation"]
    ]


# %% 定位


def _resolve(candidate: str | os.PathLike[str]) -> str:
    """转换为 DLL 的绝对路径"""
    path = os.path.abspath(os.fspath(candidate))
    if os.path.isdir(path):
        path = os.path.join(path, _DLL_NAME)
    return path


def dll_candidates(explicit: str | None = None) -> list[str]:
    """DLL 候选路径来源，按优先级为路径传入参数 > `AVASPEC_DLL` 环境变量 > 注册表"""
    sources = [explicit] if explicit else []
    sources.append(os.environ.get(_ENV_DLL, "").strip())
    sources.extend(_registry_dirs())
    return [source for source in sources if source]


def find_dll(explicit: str | None = None) -> str:
    """返回可用的 DLL 绝对路径。

    :para explicit: `None` 时通过 :func:`dll_candidates` 顺序搜索
    """
    if explicit:
        path = _resolve(explicit)
        if os.path.isfile(path):
            return path
        raise DllNotFoundError(f"指定的 DLL 不存在：{path}")

    tried: list[str] = []
    for candidate in dll_candidates():
        path = _resolve(candidate)
        if os.path.isfile(path):
            return path
        tried.append(path)
    raise DllNotFoundError(
        "找不到有效的 avaspecx DLL 文件：请通过 dll_path 参数、AVASPEC_DLL 环境变量传入正确路径，"
        "或检查是否正确安装了 AvaSoftX。\n已尝试：\n" + "\n".join(tried)
    )
