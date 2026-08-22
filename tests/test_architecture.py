"""CLAUDE.md's architecture, held as a test: the import graph (each
package may import only what its row allows), the inertness of the
backend bridge (its re-exports are data, never behavior), and the
privacy of the `Session` handles (the backend package is the only user
of its underscore surface).

A deliberate exception to the unit suite's pure-function rule: the
subject here IS the source tree, so the test reads it — and nothing
else. The tables mirror `CLAUDE.md`; a new package or arrow lands in
both in the same commit.
"""

import ast
import dataclasses
from pathlib import Path

import otaku.backend

PACKAGE = "otaku"
_ROOT = Path(__file__).resolve().parent.parent

# CLAUDE.md's import table. formatting is the stdlib-like leaf — anyone
# above may use it (its arrows are not drawn in the diagram), so it is
# listed per package here to keep the table explicit. The `web` row is
# the NOT-YET-BUILT second frontend: no package, no edges — the row
# stays as the standing test for what belongs in backend.
_ALLOWED = {
    # `python -m otaku`: the module entry, which only calls the real one.
    "__main__": {"cli"},
    "cli": {"terminal", "web", "backend", "logging", "update", "formatting"},
    "terminal": {"backend", "formatting"},
    "web": {"backend", "formatting"},
    "worker": {"context", "providers", "store", "logging", "formatting"},
    "backend": {
        "worker",
        "context",
        "providers",
        "store",
        "settings",
        "encryption",
        "logging",
        "formatting",
    },
    "context": {"store"},
    "providers": {"settings"},
    "store": {"encryption"},
    "settings": {"formatting"},
    "logging": {"encryption", "formatting"},
    "encryption": {"formatting"},
    "update": set(),
    "formatting": set(),
}


class TestArrows:
    def test_every_package_imports_only_its_allowed_arrows(self) -> None:
        violations = [
            f"{src} -> {dst}  ({where})"
            for src, dst, where in _edges()
            if dst not in _ALLOWED.get(src, set())
        ]
        assert not violations, "forbidden imports:\n" + "\n".join(violations)

    def test_every_package_has_a_declared_row(self) -> None:
        # A new top-level package must take a row here and in CLAUDE.md
        # before it may exist — even one that imports nothing yet.
        undeclared = _children() - set(_ALLOWED)
        assert not undeclared, f"packages without a declared row: {sorted(undeclared)}"


class TestBridge:
    def test_the_backend_bridge_reexports_only_inert_data(self) -> None:
        # backend/__init__ may re-export from lower packages ONLY data —
        # frozen dataclasses and exceptions. Nothing with state or
        # behavior can be laundered through it into a frontend.
        alive = [
            name for name in otaku.backend.__all__ if not _is_inert(getattr(otaku.backend, name))
        ]
        assert not alive, f"backend re-exports with behavior: {alive}"


class TestSessionPrivacy:
    def test_the_session_underscore_surface_stays_inside_backend(self) -> None:
        # The backend's own modules are the implementation and may use
        # the package-private `Session` handles; nothing else ever does —
        # the suites included, which assert through a second Store
        # connection instead.
        needle = "session" + "._"  # split so this file never matches itself
        uses = []
        for tree in (PACKAGE, "tests", "scenarios"):
            for path in sorted((_ROOT / tree).rglob("*.py")):
                if "__pycache__" in path.parts:
                    continue
                if path.is_relative_to(_ROOT / PACKAGE / "backend"):
                    continue
                for number, line in enumerate(path.read_text().splitlines(), start=1):
                    if needle in line:
                        uses.append(f"{path.relative_to(_ROOT)}:{number}: {line.strip()}")
        assert not uses, f"{needle} outside the backend:\n" + "\n".join(uses)


def _children() -> set[str]:
    """The top-level packages and modules under the distribution root."""
    out = set()
    for path in (_ROOT / PACKAGE).iterdir():
        if path.is_dir() and (path / "__init__.py").exists():
            out.add(path.name)
        elif path.suffix == ".py" and path.stem != "__init__":
            out.add(path.stem)
    return out


def _edges() -> list[tuple[str, str, str]]:
    """Every cross-package import as (source package, target package,
    file:line), read from the source tree."""
    children = _children()
    out = []
    for path in sorted((_ROOT / PACKAGE).rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        src = _package_of(path)
        for target, line in _imports(path, children):
            if target != src:
                out.append((src, target, f"{path.relative_to(_ROOT)}:{line}"))
    return out


def _package_of(path: Path) -> str:
    """The top-level package a file belongs to (a root module like
    cli.py is its own row)."""
    relative = path.relative_to(_ROOT / PACKAGE)
    return relative.parts[0] if len(relative.parts) > 1 else relative.stem


def _imports(path: Path, children: set[str]) -> list[tuple[str, int]]:
    """The distribution-internal imports of one file as (target package,
    line). A bare root import carries no edge — only __version__ lives on
    the root — but `from otaku import x` is an edge per imported child."""
    found = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(f"{PACKAGE}."):
                    found.append((alias.name.split(".")[1], node.lineno))
        elif isinstance(node, ast.ImportFrom):
            module = _absolute(node, path)
            if module == PACKAGE:
                found.extend(
                    (alias.name, node.lineno) for alias in node.names if alias.name in children
                )
            elif module.startswith(f"{PACKAGE}."):
                found.append((module.split(".")[1], node.lineno))
    return found


def _absolute(node: ast.ImportFrom, path: Path) -> str:
    """The absolute module a `from … import` names — relative imports
    resolved against the importing file's package, so none can dodge
    the check."""
    if not node.level:
        return node.module or ""
    context = list(path.parent.relative_to(_ROOT).parts)
    base = context[: len(context) - (node.level - 1)]
    return ".".join(base + ([node.module] if node.module else []))


def _is_inert(obj: object) -> bool:
    """Data, not behavior: a frozen dataclass or an exception type."""
    if not isinstance(obj, type):
        return False
    if issubclass(obj, BaseException):
        return True
    return dataclasses.is_dataclass(obj) and obj.__dataclass_params__.frozen
