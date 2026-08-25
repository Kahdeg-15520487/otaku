"""CLAUDE.md's architecture, held as a test: the import graph (each
package may import only what its row allows), the inertness of the
backend bridge (its re-exports are data, never behavior), the privacy
of the `Session` handles (the backend package is the only user of its
underscore surface), the parity of the two frontends (every command the
shared table declares is answered by both), and the web page's own
module graph — which is JavaScript, and so is read as text.

A deliberate exception to the unit suite's pure-function rule: the
subject here IS the source tree, so the test reads it — and nothing
else. The tables mirror `CLAUDE.md`; a new package or arrow lands in
both in the same commit.
"""

import ast
import dataclasses
import re
from pathlib import Path

import otaku.backend
from otaku.backend.commands import COMMANDS, CommandKind
from otaku.terminal.chat import bindings
from otaku.web import api as web_api
from otaku.web import server as web_server

PACKAGE = "otaku"
_ROOT = Path(__file__).resolve().parent.parent

# CLAUDE.md's import table. formatting is the stdlib-like leaf — anyone
# above may use it (its arrows are not drawn in the diagram), so it is
# listed per package here to keep the table explicit.
_ALLOWED = {
    # `python -m otaku`: the module entry, which only calls the real one.
    "__main__": {"cli"},
    "cli": {"terminal", "web", "backend", "logging", "update", "formatting"},
    "terminal": {"console", "backend", "formatting"},
    "web": {"console", "backend", "settings", "formatting"},
    # What a frontend draws in the terminal it was LAUNCHED from — the
    # banner both open with, and the tail under the web's. A leaf: it is
    # handed what it draws.
    "console": {"formatting"},
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


class TestFrontendParity:
    """CLAUDE.md's first two-frontend rule: a command is declared once
    and answered by BOTH. A row nobody wired is a button that does
    nothing, and the terminal's own dispatch would raise a KeyError
    where the page can only shrug — so it is caught here instead.

    The web's screen table is JavaScript, so it is read from the source
    the way this module reads everything else."""

    def test_every_command_is_answered_by_the_terminal(self) -> None:
        assert _dispatchable() - _terminal_tokens() == set()

    def test_every_command_is_answered_by_the_web(self) -> None:
        assert _dispatchable() - _web_tokens() == set()

    def test_neither_frontend_answers_a_command_that_does_not_exist(self) -> None:
        assert _terminal_tokens() - _answerable() == set()
        assert _web_tokens() - _answerable() == set()


def _dispatchable() -> set[str]:
    """Every command a frontend must answer. SYNTAX rows are the story's
    own language — they play, they do not dispatch."""
    return {spec.token for spec in COMMANDS if spec.kind is not CommandKind.SYNTAX}


def _answerable() -> set[str]:
    """What a frontend is allowed to answer: a declared row, or the
    first word of a FAMILY of them. `/set` is not a command — the table
    declares `/set think`, `/set verbose` and the rest — but a frontend
    may open one screen for the family, as the web does. Inventing any
    other token is inventing a command."""
    declared = {spec.token for spec in COMMANDS}
    return declared | {token.split(" ")[0] for token in declared if " " in token}


def _terminal_tokens() -> set[str]:
    return set(bindings.OPERATIONS) | set(bindings._INTERACTIVE)


def _web_tokens() -> set[str]:
    """The backend half is a dict; the screen half is a JavaScript
    object literal, read as text — the same way this module reads the
    import graph."""
    source = (_ROOT / "otaku" / "web" / "static" / "js" / "commands.js").read_text()
    body = source.split("const SCREENS = {", 1)[1].split("\n};", 1)[0]
    screens = set(re.findall(r'^\s*"(/[a-z ]+)":', body, re.M))
    return set(web_api.ANSWERS) | screens


class TestPageModules:
    """The page is a set of ES modules with no build step and nothing to
    enforce their direction but a habit. The graph below is that habit
    written down: a module may import only what its row allows, and the
    edges that matter are one-way — `commands` reaches the screens,
    never the other way, or a screen could not be opened from the table
    that routes to it; and `table` (the language) is a leaf, so the
    composer's menu and the transcript's highlighting depend on no
    screen."""

    def test_every_module_imports_only_what_its_row_allows(self) -> None:
        for module, imported in _page_imports().items():
            assert imported <= _PAGE[module], f"{module} imports {imported - _PAGE[module]}"

    def test_every_module_is_in_the_table(self) -> None:
        assert set(_page_imports()) == set(_PAGE)

    def test_every_module_is_served(self) -> None:
        # A module the server does not list is a 404 at the first import.
        served = {name.removeprefix("js/").removesuffix(".js") for name in web_server._SCRIPTS}
        assert set(_PAGE) <= served


# What each page module may import. `api`, `dom`, `format` and `table`
# are the leaves; `browser` is what a screen is built from; one module
# per screen; `commands` is the dispatch over all of them; `app` is the
# composition root and may reach anything.
_PAGE = {
    "api": set(),
    "dom": set(),
    "format": set(),
    "table": set(),
    "watch": {"dom"},
    "transcript": {"api", "dom", "table"},
    "browser": {"dom", "transcript"},
    "shell": {"api", "dom", "transcript"},
    "help": {"browser", "dom", "table"},
    "stories": {"api", "browser", "dom", "format", "shell"},
    "lore": {"api", "browser", "dom", "format", "transcript"},
    "models": {"api", "browser", "dom", "shell", "transcript"},
    "settings": {"api", "browser", "dom"},
    "reports": {"api", "browser", "dom", "format", "transcript"},
    "system": {"api", "browser", "dom", "shell"},
    "transfer": {"api", "browser", "dom", "shell", "transcript"},
    "commands": {
        "api",
        "browser",
        "dom",
        "help",
        "lore",
        "models",
        "reports",
        "settings",
        "shell",
        "stories",
        "system",
        "table",
        "transcript",
        "transfer",
    },
    "composer": {"api", "commands", "dom", "table", "transcript"},
    "app": {
        "api",
        "browser",
        "commands",
        "composer",
        "dom",
        "shell",
        "table",
        "transcript",
        "watch",
    },
}


def _page_imports() -> dict[str, set[str]]:
    """Every `import … from "./x.js"` in the page's own modules, read as
    text — there is no import system here to ask."""
    static = _ROOT / "otaku" / "web" / "static"
    files = [static / "app.js", *sorted((static / "js").glob("*.js"))]
    return {
        path.stem: set(re.findall(r'from "\./(?:js/)?(\w+)\.js"', path.read_text()))
        for path in files
    }


class TestDemo:
    """The deployable web demo (`demo/`) fakes the whole HTTP surface in
    the visitor's browser. Its router must know every path the spec
    lists — read as text, like everything else here — or a new endpoint
    ships with a demo that silently cannot answer it."""

    def test_the_demo_routes_every_path_the_spec_lists(self) -> None:
        spec = re.findall(r"^ {2}(/api/\S+):", (_ROOT / "docs" / "web_api.yaml").read_text(), re.M)
        router = (_ROOT / "demo" / "demo.js").read_text()
        missing = [path for path in spec if path not in router]
        assert not missing, f"paths the demo does not route: {missing}"


class TestWebApiSpec:
    """`docs/web_api.yaml` is the HTTP surface as OpenAPI, maintained by
    hand (CLAUDE.md, Web conventions). Its path list is held against the
    code's own tables — the file read as text, like everything else this
    module reads — so an endpoint added, renamed, or dropped without the
    spec fails the suite. The schemas' truth stays the review's."""

    def test_the_spec_lists_exactly_the_served_api(self) -> None:
        text = (_ROOT / "docs" / "web_api.yaml").read_text()
        spec = set(re.findall(r"^ {2}(/api/\S+):", text, re.M))
        served = {"/api/alive", "/api/watch", "/api/play", "/api/command"}
        # The reads: the table's rows plus the one read the server
        # answers itself (the extraction poll never queues).
        served |= {f"/api/read/{name}" for name in web_api.READS} | {"/api/read/extract"}
        served |= {f"/api/do/{name}" for name in web_api.ACTIONS}
        served |= {f"/api/do/{name}" for name in web_api.FLOWS}
        assert spec == served, (
            f"only in the spec: {sorted(spec - served)}; only in the code: {sorted(served - spec)}"
        )
