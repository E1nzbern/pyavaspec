"""发布元数据一致性：版本号只有 ``pyproject.toml`` 一个来源。"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

import pyavaspec

ROOT = Path(__file__).resolve().parent.parent


def test_version_matches_pyproject() -> None:
    if pyavaspec.__version__ == "0.0.0+unknown":
        pytest.skip("以源码目录导入且未安装，无法读取包元数据")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert pyavaspec.__version__ == project["version"]


def test_public_names_resolve() -> None:
    missing = [name for name in pyavaspec.__all__ if not hasattr(pyavaspec, name)]
    assert not missing


def test_all_has_no_duplicates() -> None:
    assert len(pyavaspec.__all__) == len(set(pyavaspec.__all__))
