"""分层依赖方向测试。

依赖方向只允许自上而下::

    features  ->  core  ->  _lowlevel

即：

- ``_lowlevel`` 不得引用 ``core`` / ``features`` / 顶层 ``pyavaspec``；
- ``core`` 不得引用 ``features`` 或顶层 ``pyavaspec``；
- ``features`` 不得引用顶层 ``pyavaspec``。

这样底层保持"能被单独替换"，上层保持"只依赖下层"。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
PKG = SRC / "pyavaspec"

_LAYERS = ("_lowlevel", "core", "features")

# 每层允许引用的同项目层
_ALLOWED_TARGETS: dict[str, set[str]] = {
    "_lowlevel": set(),
    "core": {"_lowlevel"},
    "features": {"_lowlevel", "core"},
}


def _iter_modules(layer: str) -> list[Path]:
    return sorted((PKG / layer).rglob("*.py"))


def _package_of(path: Path) -> list[str]:
    """文件所在的包路径（不含模块名），如 ``pyavaspec._lowlevel``。"""
    rel = path.relative_to(SRC).with_suffix("")
    parts = list(rel.parts)
    return parts[:-1]


def _resolved_imports(path: Path) -> list[str]:
    """解析文件里所有 import 的目标，相对导入折算成绝对模块名。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = _package_of(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                parts = list(package)
                drop = node.level - 1
                if drop:
                    parts = parts[:-drop] if drop <= len(parts) else []
                if node.module:
                    parts.extend(node.module.split("."))
                yield ".".join(parts)
            elif node.module:
                yield node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name


def _layer_of(dotted: str) -> str | None:
    """返回目标所属层；顶层 ``pyavaspec`` 记为空串；非本包返回 ``None``。"""
    if dotted == "pyavaspec":
        return ""
    prefix = "pyavaspec."
    if not dotted.startswith(prefix):
        return None
    head = dotted[len(prefix) :].split(".", 1)[0]
    return head if head in _LAYERS else ""


def _static_imported_names(path: Path) -> set[str]:
    """文件中被 import 的名字（含 ``from .errors import dll_errors`` 这类具名导入）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.ImportFrom, ast.Import)):
            for alias in node.names:
                names.add(alias.name)
    return names


_BUSINESS_MODULES = ("core/device.py", "core/io.py", "core/_acquisition.py")


@pytest.mark.parametrize("rel", _BUSINESS_MODULES)
def test_business_modules_do_not_translate_return_codes(rel: str) -> None:
    """返回码翻译只允许在 ``core/_driver.py``；业务 module 不得 import 翻译工具。"""
    names = _static_imported_names(PKG / rel)
    assert "dll_errors" not in names, f"{rel} 不应直接翻译返回码"
    assert "translate" not in names, f"{rel} 不应直接翻译返回码"


@pytest.mark.parametrize("layer", _LAYERS)
def test_layer_only_imports_lower_layers(layer: str) -> None:
    allowed = _ALLOWED_TARGETS[layer]
    forbidden = {"", *(_LAYERS)} - allowed - {layer}

    offenders: list[str] = []
    for path in _iter_modules(layer):
        for target in _resolved_imports(path):
            owner = _layer_of(target)
            if owner is None:
                continue
            if owner in forbidden:
                offenders.append(f"{path.relative_to(SRC)} -> {target}")

    assert not offenders, f"层 {layer!r} 出现了非法的向下/横向依赖：\n  " + "\n  ".join(offenders)
