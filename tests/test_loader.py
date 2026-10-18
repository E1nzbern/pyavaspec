"""DLL 定位和平台加载器测试。"""

from __future__ import annotations

import os
import sys

import pytest

from pyavaspec._lowlevel import _session
from pyavaspec._lowlevel._errors import DllNotFoundError, UnsupportedPlatformError
from pyavaspec._lowlevel._loader import _DLL_NAME, find_dll, load_library


def test_explicit_missing_raises(tmp_path) -> None:
    with pytest.raises(DllNotFoundError):
        find_dll(str(tmp_path / "missing" / _DLL_NAME))


def test_explicit_returns_absolute_path(tmp_path) -> None:
    dll = tmp_path / _DLL_NAME
    dll.write_bytes(b"MZ")
    found = find_dll(str(dll))
    assert os.path.isabs(found)
    assert os.path.samefile(found, dll)


def test_directory_candidate_resolves_filename(tmp_path) -> None:
    dll = tmp_path / _DLL_NAME
    dll.write_bytes(b"MZ")
    assert find_dll(str(tmp_path)) == os.path.abspath(str(dll))


def test_env_var_candidate(tmp_path, monkeypatch) -> None:
    dll = tmp_path / _DLL_NAME
    dll.write_bytes(b"MZ")
    monkeypatch.setenv("AVASPEC_DLL", str(dll))
    assert find_dll() == os.path.abspath(str(dll))


def test_unsupported_platform(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(UnsupportedPlatformError):
        load_library("whatever")


def test_session_platform_error_beats_dll_not_found(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(UnsupportedPlatformError):
        _session._load(None)
