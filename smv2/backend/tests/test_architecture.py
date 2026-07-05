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
ROUTERS_ROOT = APP_ROOT / "routers"
PIPELINE_ROOT = APP_ROOT / "pipeline"
LLM_ROOT = APP_ROOT / "llm"
LIMITER_FILE = LLM_ROOT / "limiter.py"
PROMPTS_LOADER_FILE = LLM_ROOT / "prompts.py"
INGEST_FILE = PIPELINE_ROOT / "ingest.py"
_FORBIDDEN_ROUTER_IMPORT_PREFIXES = ("sqlalchemy", "app.db")
_MAX_STRING_LITERAL_LEN = 300


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
    """app/llm/limiter.py is the one sanctioned exception — it IS the
    concurrency limiter. Everywhere else, threading/semaphore usage would
    mean a second, uncoordinated concurrency gate (the double-acquire
    deadlock class this project has been burned by before).
    """
    violations: dict[str, list[str]] = {}
    for path in _python_files():
        if path == LIMITER_FILE:
            continue
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


def _imported_module_names(tree: ast.Module) -> list[tuple[int, str]]:
    names: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append((node.lineno, node.module))
    return names


def test_routers_stay_thin_no_db_layer_imports() -> None:
    """Routers must delegate to services, never touch SQLAlchemy or the DB
    layer directly — otherwise "thin router" becomes a suggestion, not a rule.
    """
    violations: dict[str, list[str]] = {}
    for path in sorted(ROUTERS_ROOT.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        found = [
            f"line {lineno}: {name}"
            for lineno, name in _imported_module_names(tree)
            if name.startswith(_FORBIDDEN_ROUTER_IMPORT_PREFIXES)
        ]
        if found:
            violations[str(path)] = found

    assert not violations, f"routers must delegate to services, not the DB layer: {violations}"


def test_derived_tables_registry_covers_all_fk_models() -> None:
    """Every ORM model with a FK to courses.id or sections.id must be
    registered in exactly one of REPLACED_ON_REINGEST, REMAPPED_ON_REINGEST,
    or LEDGER_TABLES — otherwise re-ingest silently orphans or duplicates it.
    """
    from app.db.models import Base
    from app.db.registry import LEDGER_TABLES, REMAPPED_ON_REINGEST, REPLACED_ON_REINGEST

    registered_tablenames = [
        model.__tablename__
        for model in (*REPLACED_ON_REINGEST, *REMAPPED_ON_REINGEST, *LEDGER_TABLES)
    ]

    fk_tables: set[str] = set()
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            if fk.column.table.name in {"courses", "sections"}:
                fk_tables.add(table.name)

    unregistered = fk_tables - set(registered_tablenames)
    assert not unregistered, f"tables with FK to courses/sections not registered: {unregistered}"

    duplicated = {name for name in registered_tablenames if registered_tablenames.count(name) > 1}
    assert not duplicated, f"tables registered in more than one list: {duplicated}"


def test_pipeline_stays_framework_free() -> None:
    """app/pipeline/* must not import fastapi — ingest/outline/extraction
    logic has to be testable and runnable with no web framework in play.
    """
    violations: dict[str, list[str]] = {}
    for path in sorted(PIPELINE_ROOT.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        found = [
            f"line {lineno}: {name}"
            for lineno, name in _imported_module_names(tree)
            if name == "fastapi" or name.startswith("fastapi.")
        ]
        if found:
            violations[str(path)] = found

    assert not violations, f"app/pipeline/* must not import fastapi: {violations}"


def test_llm_sdk_imports_confined_to_llm_package() -> None:
    """anthropic and httpx (the Ollama HTTP client) may only be imported
    under app/llm/ — every other module talks to an LLM through the
    Provider abstraction, never a raw SDK/HTTP client of its own.
    """
    violations: dict[str, list[str]] = {}
    for path in _python_files():
        if path.is_relative_to(LLM_ROOT):
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        found = [
            f"line {lineno}: {name}"
            for lineno, name in _imported_module_names(tree)
            if name in {"anthropic", "httpx"} or name.startswith(("anthropic.", "httpx."))
        ]
        if found:
            violations[str(path)] = found

    assert not violations, f"anthropic/httpx imports must live only under app/llm/: {violations}"


def _docstring_node_ids(tree: ast.Module) -> set[int]:
    """id() of every string-constant node that's a module/class/function
    docstring (its body's first statement) — these are documentation, not
    the "prompt baked into code" pattern this check targets, so they're
    exempt regardless of length.
    """
    docstring_ids: set[int] = set()

    def _mark_if_docstring(body: list[ast.stmt]) -> None:
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            docstring_ids.add(id(body[0].value))

    _mark_if_docstring(tree.body)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            _mark_if_docstring(node.body)

    return docstring_ids


def test_no_long_string_literals_in_pipeline_or_llm() -> None:
    """Prompts live as files under backend/prompts/vN/ (loaded via
    app/llm/prompts.py), never as string literals baked into code — that's
    what keeps prompt changes reviewable as plain diffs and prompt_version
    tracking meaningful. Docstrings are exempt (documentation, not prompts).
    """
    violations: dict[str, list[str]] = {}
    for root in (PIPELINE_ROOT, LLM_ROOT):
        for path in sorted(root.glob("*.py")):
            if path.name == "__init__.py" or path == PROMPTS_LOADER_FILE:
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            docstring_ids = _docstring_node_ids(tree)
            found = [
                f"line {node.lineno}: string literal of length {len(node.value)}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and len(node.value) > _MAX_STRING_LITERAL_LEN
                and id(node) not in docstring_ids
            ]
            if found:
                violations[str(path)] = found

    assert not violations, f"long string literals belong in prompts/ files, not code: {violations}"


def test_ingest_pipeline_never_imports_llm() -> None:
    """ADR-010: ingest makes ZERO LLM calls. Mechanically enforced — the
    ingest module (unlike generation.py, which legitimately needs the LLM
    layer) must never import anything from app.llm.
    """
    tree = ast.parse(INGEST_FILE.read_text(), filename=str(INGEST_FILE))
    found = [
        f"line {lineno}: {name}"
        for lineno, name in _imported_module_names(tree)
        if name == "app.llm" or name.startswith("app.llm.")
    ]
    assert not found, f"app/pipeline/ingest.py must never import app.llm: {found}"
