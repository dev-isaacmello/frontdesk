"""GRD-5: the guardrail imports nothing from the rest of the project, only the standard library."""

import ast
import sys
from pathlib import Path

import frontdesk.guardrail

PACKAGE = "frontdesk.guardrail"
SOURCES = sorted(Path(frontdesk.guardrail.__file__).parent.glob("**/*.py"))


def imported_modules(source: Path) -> list[str]:
    """Absolute module names a file imports; a relative import is spelled from the package."""
    modules: list[str] = []
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = PACKAGE if node.level == 1 else "outside" if node.level else ""
            modules.append(".".join(part for part in (prefix, node.module) if part))
    return modules


def is_allowed(module: str) -> bool:
    if module == PACKAGE or module.startswith(PACKAGE + "."):
        return True
    return module.split(".")[0] in sys.stdlib_module_names


def test_grd_5_the_package_imports_only_itself_and_the_standard_library() -> None:
    assert SOURCES, "the guardrail package has no source files to scan"

    offenders = [
        (source.name, module)
        for source in SOURCES
        for module in imported_modules(source)
        if not is_allowed(module)
    ]

    assert offenders == []


def test_grd_5_the_scan_would_catch_a_project_or_third_party_import() -> None:
    assert not is_allowed("frontdesk.domain.catalog")
    assert not is_allowed("frontdesk")
    assert not is_allowed("pydantic")
    assert not is_allowed("outside.frontdesk")
    assert is_allowed("frontdesk.guardrail.facts")
    assert is_allowed("datetime")
