"""Mechanical checks for the hard invariants in this backend.

These are cheap AST scans, not a substitute for review, but they catch the
two regressions this project has explicitly promised never to reintroduce:
reading os.environ at import time, and adding concurrency primitives outside
the single sanctioned limiter.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
CONFIG_FILE = APP_ROOT / "config.py"


def _is_os_name(node: ast.expr) -> bool:
    return isinstance(node, ast.Name) and node.id == "os"


class ModuleScopeEnvVisitor(ast.NodeVisitor):
    """Flags os.environ / os.getenv() usage that is NOT inside a function/class body."""

    def __init__(self) -> None:
        self.violations: list[str] = []
        self._def_depth = 0

    def _visit_nested(self, node: ast.AST) -> None:
        self._def_depth += 1
        self.generic_visit(node)
        self._def_depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_nested(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_nested(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_nested(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if self._def_depth == 0 and node.attr == "environ" and _is_os_name(node.value):
            self.violations.append(f"line {node.lineno}: os.environ read at module scope")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if self._def_depth == 0:
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "getenv" and _is_os_name(func.value):
                self.violations.append(f"line {node.lineno}: os.getenv() call at module scope")
        self.generic_visit(node)


def _python_files() -> list[Path]:
    return sorted(APP_ROOT.rglob("*.py"))


def test_no_module_scope_env_reads_outside_config() -> None:
    violations: dict[str, list[str]] = {}
    for path in _python_files():
        if path == CONFIG_FILE:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        visitor = ModuleScopeEnvVisitor()
        visitor.visit(tree)
        if visitor.violations:
            violations[str(path)] = visitor.violations

    assert not violations, f"module-scope os.environ/os.getenv reads found: {violations}"


def test_no_threading_or_semaphore_usage_outside_limiter() -> None:
    violations: dict[str, list[str]] = {}
    for path in _python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        found: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "threading":
                        found.append(f"line {node.lineno}: import threading")
            elif isinstance(node, ast.ImportFrom) and node.module == "threading":
                found.append(f"line {node.lineno}: from threading import ...")
            elif isinstance(node, ast.Attribute) and node.attr in {"Semaphore", "BoundedSemaphore"}:
                found.append(f"line {node.lineno}: {node.attr} usage")
            elif isinstance(node, ast.Name) and node.id in {"Semaphore", "BoundedSemaphore"}:
                found.append(f"line {node.lineno}: {node.id} usage")
        if found:
            violations[str(path)] = found

    assert not violations, f"disallowed threading/semaphore usage found: {violations}"
