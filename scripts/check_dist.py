"""校验 ``uv build`` 产物。

在 ``uv build`` 之后运行::

    uv run python scripts/check_dist.py

检查项：

- ``dist/`` 中存在当前版本的 wheel 和 sdist；
- wheel 只包含 ``pyavaspec`` 包本身（外加 dist-info），不混入测试、缓存等；
- sdist 包含源码、测试、示例、文档和根目录元数据文件，不混入缓存、虚拟环境等；
- 包元数据中的名称、版本与 ``pyproject.toml`` 一致；
- 仓库根目录存在 ``LICENSE`` 时，必须被打进 wheel 和 sdist。

退出码：0 = 通过；1 = 发现问题。
"""

from __future__ import annotations

import sys
import tarfile
import tomllib
import zipfile
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
PACKAGE = "pyavaspec"

FORBIDDEN_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vscode",
    "__pycache__",
    "dist",
}
FORBIDDEN_NAMES = {".coverage", ".DS_Store"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo"}

problems: list[str] = []


def fail(message: str) -> None:
    problems.append(message)


def check(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def project_metadata() -> dict[str, object]:
    raw = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return tomllib.loads(raw)["project"]


def artifacts(pattern: str) -> list[Path]:
    return sorted(DIST.glob(pattern))


def check_forbidden(names: Iterable[str], label: str) -> None:
    for name in names:
        path = Path(name)
        if path.name in FORBIDDEN_NAMES or path.suffix in FORBIDDEN_SUFFIXES:
            fail(f"{label} 混入禁止文件：{name}")
        if FORBIDDEN_DIRS.intersection(path.parts):
            fail(f"{label} 混入禁止目录：{name}")


def read_wheel_metadata(archive: zipfile.ZipFile) -> dict[str, str]:
    name = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
    fields: dict[str, str] = {}
    for line in archive.read(name).decode("utf-8").splitlines():
        if not line:
            break
        key, _, value = line.partition(": ")
        fields[key] = value
    return fields


def check_wheel(wheel: Path, version: str, has_license: bool) -> None:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        check_forbidden(names, wheel.name)

        source = ROOT / "src" / PACKAGE
        expected = {
            path.relative_to(ROOT / "src").as_posix()
            for path in source.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }
        actual = {name for name in names if name.split("/", 1)[0] == PACKAGE}
        check(not expected - actual, f"wheel 缺少文件：{sorted(expected - actual)}")
        check(not actual - expected, f"wheel 多出文件：{sorted(actual - expected)}")

        metadata = read_wheel_metadata(archive)
        check(metadata.get("Name") == PACKAGE, f"wheel 名称错误：{metadata.get('Name')!r}")
        check(metadata.get("Version") == version, f"wheel 版本错误：{metadata.get('Version')!r}")
        check(
            metadata.get("Requires-Python") == ">=3.12",
            f"wheel Requires-Python 错误：{metadata.get('Requires-Python')!r}",
        )
        license_expression = metadata.get("License-Expression") or metadata.get("License")
        check(
            license_expression == "Apache-2.0",
            f"wheel 许可证声明错误：{license_expression!r}",
        )

        if has_license:
            check(
                any(name.endswith("/licenses/LICENSE") for name in names),
                "wheel 缺少 LICENSE",
            )


def check_sdist(sdist: Path, version: str, has_license: bool) -> None:
    top = f"{PACKAGE}-{version}"
    with tarfile.open(sdist) as archive:
        names = archive.getnames()
        check_forbidden(names, sdist.name)

        required = [
            f"{top}/README.md",
            f"{top}/pyproject.toml",
            f"{top}/src/{PACKAGE}/__init__.py",
        ]
        for path in required:
            check(path in names, f"sdist 缺少文件：{path}")

        for directory in ("tests", "examples", "docs"):
            check(
                any(name.startswith(f"{top}/{directory}/") for name in names),
                f"sdist 缺少目录：{directory}/",
            )

        if has_license:
            check(f"{top}/LICENSE" in names, "sdist 缺少 LICENSE")


def main() -> int:
    project = project_metadata()
    version = str(project["version"])
    has_license = (ROOT / "LICENSE").is_file()

    if not DIST.is_dir():
        print("[失败] 没有 dist/ 目录，请先运行 uv build")
        return 1

    wheels = artifacts(f"{PACKAGE}-{version}-*.whl")
    sdists = artifacts(f"{PACKAGE}-{version}.tar.gz")

    check(len(wheels) == 1, f"应恰好有 1 个 {version} wheel，实际 {len(wheels)} 个")
    check(len(sdists) == 1, f"应恰好有 1 个 {version} sdist，实际 {len(sdists)} 个")

    if wheels:
        check_wheel(wheels[0], version, has_license)
    if sdists:
        check_sdist(sdists[0], version, has_license)

    if problems:
        print(f"[失败] 发现 {len(problems)} 个问题：")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print(f"[通过] wheel：{wheels[0].name}")
    print(f"[通过] sdist：{sdists[0].name}")
    if not has_license:
        print("[提示] 根目录暂无 LICENSE；添加后请重新构建并再次运行本脚本。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
