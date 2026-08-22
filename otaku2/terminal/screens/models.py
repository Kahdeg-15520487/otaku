"""The model picker + provider panel — opened by the launch-time pick
and `/model`.

A single full-screen Application, split 1:1. The left side lists every
model from every reachable provider — grouped under engine captions in
the panel's order (`api.providers.engines`, the one source of the
captions), bare model names, providers with no models absent —
color-coded by load state. Only the local engines are waited for before
the screen opens; each cloud catalog's rows arrive when it answers, the
panel naming what is still loading. The user can:
    - move the cursor (↑/↓/PgUp/PgDn/Home/End)
    - type-to-filter by pressing `/` first; Esc cancels the filter
    - toggle load state with `l`/`u` (a confirm dialog, then a spinner)
    - press Enter to pick the highlighted model — the switch is EXECUTED
      here (`api.providers.switch_model`, the screens' one ownership
      rule) and its notice returned. A model that is not loaded yet is
      loaded first (same modal + spinner) and only switched on success.
    - press Esc to leave without picking.

Loaded models render bold; not-loaded muted. The cursor restores to the
last-used model on open. An engine without load/unload serves its models
statically: they all show as loaded, Enter picks them directly, and the
l/u keys (and their help entries) disappear on such a row.

The right side is the provider panel: each engine's caption with its
`URL:` and `API key:` fields, the key's value never displayed, the
cloud catalogs' url fixed (shown dimmed, never walkable). Tab switches
sides; ↑/↓ walk the fields; Enter edits the highlighted one in place
(←/→ move the cursor, paste works, Enter saves); a paste onto a CLOSED
field (Cmd+V, Ctrl+V) sets it outright — a url or a key is pasted whole
rather than composed — while inside the editor a paste is an ordinary
paste; Delete on an api key, outside the editor, clears it. Saves go
through `api.providers.save_field` (sealed keys, surgical writes, live
registry — all the backend's), and the provider's models are re-listed
under the new configuration.
"""

import contextlib
import threading
import time
from dataclasses import dataclass
from typing import Any

import psutil
from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.data_structures import Point
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import (
    ConditionalKeyBindings,
    KeyBindings,
    merge_key_bindings,
)
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.containers import (
    ConditionalContainer,
    HSplit,
    ScrollOffsets,
    VSplit,
    Window,
)
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import D
from prompt_toolkit.styles import Style

from otaku2.backend import Provider
from otaku2.backend.api import providers as api_providers
from otaku2.backend.api.providers import Engine
from otaku2.backend.session import Refused, Session
from otaku2.formatting import format_context, format_size, truncate
from otaku2.terminal.screens.base import ListScreen, base_style, bordered_box, text_line
from otaku2.terminal.tty import clipboard, latin_key
from otaku2.terminal.tty.spinner import FRAMES as SPINNER_FRAMES
from otaku2.terminal.tty.theme import theme


def pick(session: Session, initial_spec: str | None = None) -> str | None:
    """Show the picker; a confirmed choice is EXECUTED here
    (api.providers.switch_model — the screens' one ownership rule) and
    the switch notice returned; None when the user leaves without
    choosing — silently: at launch the session opens model-less and the
    first turn explains itself, from /model everything stays as it was.
    Opens even with nothing to list — the panel is the one door to
    configuring an engine. Only the local engines are waited for: the
    screen opens on their answers, and each cloud catalog's rows arrive
    when it responds."""
    engines = api_providers.engines(session)
    catalogs = [engine.name for engine in engines if not engine.local]
    rows, reachable = api_providers.get_providers(session, skip=set(catalogs))
    entries: list[ModelEntry] = []
    for row in rows:
        for model in row.models:
            entries.append(
                ModelEntry(
                    full_spec=f"{row.config.name}/{model.name}",
                    provider_name=row.config.name,
                    model=model.name,
                    # An engine you can't load/unload serves its models
                    # statically, so they are ALWAYS available — shown
                    # loaded, and Enter picks them directly.
                    loaded=model.loaded if row.can_load_unload else True,
                    can_load_unload=row.can_load_unload,
                    size_bytes=model.size,
                    context=model.context,
                    cloud=not row.local,
                )
            )
    order = {engine.name: i for i, engine in enumerate(engines)}
    picker = ModelPicker(
        session,
        engines,
        _ordered(entries, order),
        initial_spec=initial_spec,
        fetch=catalogs,
        connected=reachable,
    )
    return picker.run()


_FIELD_LABELS = {"url": "URL:", "api_key": "API key:"}

# A model row's shape: a 4-column prefix ("  > "), the model name, then
# two right-aligned columns held at a FIXED width — the widest label
# either formatter can produce for a real model ("999.9 GB", "128K";
# see formatting.format_size / format_context) — each set off by three
# spaces. Fixed because the columns must not move: a cloud catalog
# arriving mid-session, or a resize, may not shove them off the pane.
# The name is the one thing that gives, shrinking to whatever is left —
# to a stub on a pane too narrow to hold one, because a row wider than
# the pane would wrap, and the scroll maths counts one line per model.
_ROW_PREFIX = 4
_SIZE_COL = 8
_CONTEXT_COL = 4
_COL_GAP = 3


def _style() -> Style:
    """Shared chrome from `base_style` plus the picker's row, preview and
    panel overrides, in the shades the terminal background asked for."""
    colors = theme()
    panel = f"bg:{colors.panel.style}"
    band = f"bg:{colors.selection.style}"
    raised = f"bg:{colors.raised.style}"
    return Style.from_dict(
        {
            **base_style(),
            "row.loaded": f"bold fg:{colors.text.style} {panel}",
            "row.notloaded": f"dim fg:{colors.muted.style} {panel}",
            "row.plain": f"fg:{colors.text.style} {panel}",
            "row.selected.loaded": f"bold fg:{colors.ink.style} {band}",
            "row.selected.notloaded": f"dim fg:{colors.ink.style} {band}",
            "row.selected.plain": f"fg:{colors.ink.style} {band}",
            # the light parts of the bold header
            "header.detail": f"nobold fg:{colors.title.style} {panel}",
            "row.selected": f"bold fg:{colors.ink.style} {band}",
            "dialog.error": f"bold fg:{colors.error.style} {raised}",
            "preview.title": f"bold fg:{colors.title.style} {panel}",
            "preview.body": f"fg:{colors.text.style} {panel}",
            "preview.muted": f"dim fg:{colors.muted.style} {panel}",  # the unloaded models' look
            # The text cursor, drawn as a block: whatever it sits on,
            # inverted — the one styling that needs no color at all.
            "field.cursor": "reverse",
            "tick": f"fg:{colors.ok.style} {panel}",
            "notice": f"dim fg:{colors.muted.style} {panel}",
        }
    )


@dataclass
class ModelEntry:
    full_spec: str  # "provider/model"
    provider_name: str
    model: str
    loaded: bool
    can_load_unload: bool = True  # False → served statically
    size_bytes: int | None = None  # None when the provider doesn't expose it
    context: int | None = None  # the model's context window, when reported
    cloud: bool = False  # a hosted catalog's row: normal weight, no size


class ModelPicker(ListScreen):
    def __init__(
        self,
        session: Session,
        engines: list[Engine],
        entries: list[ModelEntry],
        initial_spec: str | None = None,
        *,
        fetch: list[str] | None = None,
        connected: set[str] | None = None,
    ) -> None:
        super().__init__()
        self.session = session
        # The panel vocabulary — captions, order, and the local/cloud
        # split — from the backend's one source.
        self.engines = engines
        self._order = {engine.name: i for i, engine in enumerate(engines)}
        self._captions = {engine.name: engine.label for engine in engines}
        # Names whose last listing succeeded — the panel's tick: the
        # provider answered, and with the right key where one is needed.
        self.connected: set[str] = set(connected or ())
        self.all: list[ModelEntry] = list(entries)
        self.filtered: list[ModelEntry] = list(entries)
        self._initial_spec = initial_spec

        # The provider panel (the right side): the walkable field list —
        # two rows per engine, except the cloud catalogs whose url is
        # fixed (their API key alone) — its own cursor (both sides stay
        # visible, so the base's one integer serves the models side and
        # the key handling swaps), the inline editor.
        self.side: str = "models"
        self.fields: list[tuple[str, str]] = [
            (engine.name, attr)
            for engine in engines
            for attr in ("url", "api_key")
            if attr != "url" or engine.local
        ]
        self.field_cursor: int = 0
        self.editing: bool = False
        self.edit_buffer = Buffer(multiline=False)

        if initial_spec is not None:
            for i, entry in enumerate(self.all):
                if entry.full_spec == initial_spec:
                    self.cursor = i
                    break

        # Confirmation state (set when the user presses load/unload)
        self.confirming_action: str | None = None  # "load" or "unload"
        self.confirming_entry: ModelEntry | None = None

        # Modal state for the in-flight HTTP action
        self.busy: bool = False
        self.busy_action: str = ""  # "Loading" or "Unloading"
        self.busy_target: str = ""  # full_spec of the model being acted on
        self.busy_error: str | None = None
        self.spinner_frame: int = 0
        self._exit_on_success: bool = False
        self._lock = threading.Lock()

        # The switch notice on a confirmed pick; None while browsing.
        self.result: str | None = None
        self.app = self._build_app()

        # The named providers (the cloud catalogs) answer after the screen
        # is up: each fetch merges its rows in and leaves the pending set.
        self.pending: set[str] = set(fetch or [])
        # A snapshot: a fetch that fails instantly (a keyless catalog)
        # discards from the live set while this loop still walks it.
        for name in list(self.pending):
            self._refresh_provider(name)

    def run(self) -> str | None:
        # An empty screen still runs: the provider panel is the one door
        # to configuring an engine, so a machine with nothing reachable
        # must reach it — `pick` alone decides when opening is skipped.
        self.app.run()
        return self.result

    # ---------- text content ----------

    def _row_width(self) -> int:
        """Full width of a rendered model row: the whole items pane, so
        the selection band ends exactly `_preview_gap` columns short of
        the provider panel's border, like every other picker's rows. The
        pane alone decides — never the data — so no model name can push a
        row past the edge of the screen."""
        return self._max_row_content_width()

    def _name_width(self) -> int:
        """Columns the model name gets: the row, less its prefix and the
        two fixed columns with their gaps. This is where a narrow
        terminal and a late-arriving cloud catalog are absorbed."""
        tail = _COL_GAP + _SIZE_COL + _COL_GAP + _CONTEXT_COL
        return max(0, self._row_width() - _ROW_PREFIX - tail)

    def _header_text(self) -> StyleAndTextTuples:
        n, total = len(self.filtered), len(self.all)
        left = f" Models ({n} of {total})" if n != total else f" Models ({n})"
        # What is still loading is said in the provider panel, on the row
        # of the provider it is about (see `_providers_text`).
        try:
            vm = psutil.virtual_memory()
            used_gb = vm.used / (1024**3)
            total_gb = vm.total / (1024**3)
            ram = f"RAM: {used_gb:.1f} / {total_gb:.1f} GB ({vm.percent:.0f}%)"
        except Exception:
            ram = ""

        head: StyleAndTextTuples = [("class:header", left)]
        if not ram:
            return head

        # Right-align RAM to the rows' right edge.
        gap = " " * max(2, self._row_width() - len(left) - len(ram))
        return [*head, ("class:header.detail", gap + ram)]

    def _items_text(self) -> StyleAndTextTuples:
        # One snapshot for the whole frame: a background refresh swaps
        # self.filtered, and the column lists must match the row loop.
        rows = self.filtered
        if not rows:
            msg = "(no matches)" if self.query else "(no models)"
            return [("class:muted", "  " + msg)]

        # Every row spans one width: the model name on the left, cut to
        # what the pane leaves it, then the two fixed columns at the
        # right edge — same place on every row, whatever arrives later.
        labels = [truncate(e.model, self._name_width()) for e in rows]
        # A catalog row has no size at all — not even the unknown dash.
        sizes = ["" if e.cloud else format_size(e.size_bytes) for e in rows]
        contexts = [format_context(e.context) for e in rows]
        width = self._row_width()

        out: StyleAndTextTuples = []
        prev_provider: str | None = None
        for i, entry in enumerate(rows):
            if entry.provider_name != prev_provider:
                # The provider panel's structure, mirrored: a caption, a
                # blank, the rows — a provider with no models is absent.
                if prev_provider is not None:
                    out.append(("", "\n"))
                caption = self._captions.get(entry.provider_name, entry.provider_name)
                out.append(("class:preview.title", "  " + caption + "\n"))
                out.append(("", "\n"))
                prev_provider = entry.provider_name
            # The cursor shows only while this side has the focus — on the
            # providers side the left list carries no selection at all.
            selected = i == self.cursor and self.side == "models"
            head = ("  > " if selected else "    ") + labels[i]
            tail = (
                " " * _COL_GAP
                + sizes[i].rjust(_SIZE_COL)
                + " " * _COL_GAP
                + contexts[i].rjust(_CONTEXT_COL)
            )
            gap = max(0, width - len(head) - len(tail))
            if entry.cloud:
                klass = "class:row.selected.plain" if selected else "class:row.plain"
            elif selected:
                klass = (
                    "class:row.selected.loaded" if entry.loaded else "class:row.selected.notloaded"
                )
            else:
                klass = "class:row.loaded" if entry.loaded else "class:row.notloaded"
            out.append((klass, head + " " * gap + tail + "\n"))
        return out

    def _cursor_line(self) -> int:
        """Visual row of the cursor, counting the caption and blank lines
        `_items_text` renders around each provider group."""
        line = 0
        prev: str | None = None
        for i, entry in enumerate(self.filtered[: self.cursor + 1]):
            if entry.provider_name != prev:
                line += 2 if prev is None else 3  # (group gap +) caption + blank
                prev = entry.provider_name
            if i == self.cursor:
                return line
            line += 1
        return line

    def _help_text(self) -> StyleAndTextTuples:
        if self.editing:
            txt = " editing — enter save · esc cancel"
        elif self.side == "providers":
            txt = " ↑/↓ navigate · enter edit · del clear key · tab models · esc back"
        elif self.in_filter:
            txt = " type to filter · ↑/↓ navigate · enter select · esc clear filter"
        else:
            segments = ["↑/↓ navigate", "/ filter"]
            # Load/unload only appear when the SELECTED model's engine
            # supports them.
            if self.filtered and self.filtered[self.cursor].can_load_unload:
                segments += ["l load", "u unload"]
            segments += ["enter select", "tab providers", "esc quit"]
            txt = " " + " · ".join(segments)
        return [("class:help", txt)]

    def _confirm_text(self) -> StyleAndTextTuples:
        if not self.confirming_action or self.confirming_entry is None:
            return [("", "")]
        verb = "Load" if self.confirming_action == "load" else "Unload"
        # Dialog inner content area is ~54 chars wide at preferred 60.
        spec = truncate(self.confirming_entry.full_spec, 40)
        return [
            ("class:dialog.title", f"{verb} model {spec!r}?\n"),
            ("class:dialog.body", "\n"),
            ("class:dialog.muted", "y to confirm     n / esc to cancel"),
        ]

    def _dialog_text(self) -> StyleAndTextTuples:
        if self.busy_error is not None:
            return [
                ("class:dialog.title", f"{self.busy_action} failed\n"),
                ("class:dialog.body", "\n"),
                ("class:dialog.error", self.busy_error[:120] + "\n"),
                ("class:dialog.body", "\n"),
                ("class:dialog.muted", "press any key to dismiss"),
            ]
        spin = SPINNER_FRAMES[self.spinner_frame % len(SPINNER_FRAMES)]
        return [
            ("class:dialog.title", f"{self.busy_action}\n"),
            ("class:dialog.body", "\n"),
            ("class:dialog.body", truncate(self.busy_target, 50) + "\n"),
            ("class:dialog.body", "\n"),
            ("class:dialog.muted", f"  {spin}  please wait…"),
        ]

    def _providers_text(self) -> StyleAndTextTuples:
        """The provider panel: per engine a caption, a blank, the URL
        field, the API key field (its value never displayed), a blank."""
        out: StyleAndTextTuples = []
        for engine in self.engines:
            config = api_providers.section(self.session, engine.name)
            if engine.name in self.pending:
                # Still being listed: the answer decides the other two, so
                # say so here rather than let the name read as a verdict.
                out.append(("class:preview.muted", engine.label + " - loading…"))
            elif engine.name in self.connected:
                out.append(("class:preview.title", engine.label))
                out.append(("class:tick", " ✓"))
            else:
                # Not connected: the name alone reads disabled.
                out.append(("class:preview.muted", engine.label))
            out.append(("", "\n"))
            out.append(("class:preview.body", "\n"))
            out.extend(self._field_line(engine.name, "url", config.url))
            out.extend(self._field_line(engine.name, "api_key", "(set)" if config.api_key else ""))
            out.append(("class:preview.body", "\n"))
        return out

    def _field_line(self, kind: str, attr: str, value: str) -> StyleAndTextTuples:
        """One field row: the label outside the selection, the value cell
        highlighted when the cursor is on it — labels padded to one
        column so the input fields left-align. A field that is not
        walkable (a cloud catalog's fixed url) renders dimmed."""
        if (kind, attr) not in self.fields:
            head = f"  {_FIELD_LABELS[attr]:<9}"
            return [("class:preview.muted", head + value + "\n")]
        selected = self.side == "providers" and self.fields[self.field_cursor] == (kind, attr)
        head = f"{'> ' if selected else '  '}{_FIELD_LABELS[attr]:<9}"
        if selected and self.editing:
            return [("class:preview.body", head), *self._editor_segments(attr, len(head))]
        if selected:
            width = max(1, self._preview_inner_width() - len(head))
            return [("class:preview.body", head), ("class:row.selected", value.ljust(width) + "\n")]
        return [("class:preview.body", (head + value).rstrip() + "\n")]

    def _editor_segments(self, attr: str, head_len: int) -> StyleAndTextTuples:
        """The value cell while editing: the buffer's text — bullets for
        an api key — with the character under the cursor as the caret."""
        text = self.edit_buffer.text
        pos = min(self.edit_buffer.cursor_position, len(text))
        shown = "•" * len(text) if attr == "api_key" else text
        width = max(len(shown) + 1, self._preview_inner_width() - head_len)
        caret = shown[pos] if pos < len(shown) else " "
        return [
            ("class:row.selected", shown[:pos]),
            ("class:field.cursor", caret),
            ("class:row.selected", shown[pos + 1 :].ljust(width - pos - 1) + "\n"),
        ]

    def _panel_cursor_line(self) -> int:
        """Visual row of the highlighted field — each provider block is 5
        rows (caption, blank, url, api key, blank)."""
        kind, attr = self.fields[self.field_cursor]
        return self._order[kind] * 5 + 2 + (0 if attr == "url" else 1)

    # ---------- behavior ----------

    def _rows_count(self) -> int:
        return len(self.fields) if self.side == "providers" else len(self.filtered)

    def _move_cursor(self, delta: int) -> None:
        # The panel side moves its OWN cursor — both sides stay visible,
        # so the base's one integer keeps the models side.
        self.notice = ""
        if self.side == "providers":
            self.field_cursor = max(0, min(len(self.fields) - 1, self.field_cursor + delta))
        else:
            super()._move_cursor(delta)

    def _type(self, data: str) -> None:
        # Letters and the `/` filter belong to the models side.
        if self.side == "models":
            super()._type(data)

    def _toggle_side(self) -> None:
        self.notice = ""
        self._clear_filter()
        self.side = "providers" if self.side == "models" else "models"

    def _refilter(self) -> None:
        q = self.query.strip().lower()
        if not q:
            self.filtered = list(self.all)
        else:
            self.filtered = [e for e in self.all if q in e.full_spec.lower()]
        if self.cursor >= len(self.filtered):
            self.cursor = max(0, len(self.filtered) - 1)

    def _start_action(self, entry: ModelEntry, *, load: bool, exit_on_success: bool) -> None:
        with self._lock:
            if self.busy:
                return
            self.busy = True
            self.busy_action = "Loading" if load else "Unloading"
            self.busy_target = entry.full_spec
            self.busy_error = None
            self.spinner_frame = 0
            self._exit_on_success = exit_on_success

        def worker() -> None:
            err: str | None = None
            try:
                if load:
                    api_providers.load(self.session, entry.provider_name, entry.model)
                else:
                    api_providers.unload(self.session, entry.provider_name, entry.model)
                # ollama's /api/ps lags ~100-200ms behind /api/generate's
                # response — without this sleep the refresh below sees the
                # model still loaded after an unload.
                time.sleep(0.2)
                # Refresh load state for this provider only — under the
                # lock, a concurrent catalog refresh may be swapping the
                # list.
                fresh = {
                    model.name
                    for row in self._fetch_rows(entry.provider_name)
                    for model in row.models
                    if model.loaded
                }
                with self._lock:
                    for e in self.all:
                        if e.provider_name == entry.provider_name:
                            e.loaded = e.model in fresh
            except Refused as ex:
                err = str(ex)
            except Exception as ex:
                err = f"{type(ex).__name__}: {ex}"

            with self._lock:
                self.busy = False
                self.busy_error = err
                exit_now = err is None and self._exit_on_success
            if exit_now:
                self._finish_pick(entry)
                return
            with contextlib.suppress(Exception):
                self.app.invalidate()

        def animator() -> None:
            while True:
                with self._lock:
                    if not self.busy:
                        return
                    self.spinner_frame = (self.spinner_frame + 1) % len(SPINNER_FRAMES)
                try:
                    self.app.invalidate()
                except Exception:
                    return
                time.sleep(0.1)

        threading.Thread(target=worker, daemon=True).start()
        threading.Thread(target=animator, daemon=True).start()

    def _finish_pick(self, entry: ModelEntry) -> None:
        """Execute the confirmed choice (the screens' one ownership rule)
        and leave with the switch notice — an "Already using" refusal is
        a notice too: either way the session is on that model now."""
        try:
            self.result = api_providers.switch_model(self.session, entry.provider_name, entry.model)
        except Refused as e:
            self.result = str(e)
        with contextlib.suppress(Exception):
            self.app.exit()

    def _on_enter(self) -> None:
        if self.side == "providers":
            self._start_field_edit()
            return
        if not self.filtered:
            return
        entry = self.filtered[self.cursor]
        if entry.loaded or not entry.can_load_unload:
            # Loaded — or a statically served engine (llama.cpp, a
            # KoboldCpp between admin swaps): the engine serves what it
            # serves, so Enter just picks.
            self._finish_pick(entry)
            return
        # Not loaded — load it, then switch on success.
        self._start_action(entry, load=True, exit_on_success=True)

    def _request_load(self) -> None:
        if self.in_filter or self.confirming_action or not self.filtered:
            return
        entry = self.filtered[self.cursor]
        if not entry.can_load_unload or entry.loaded:
            return  # can't load this engine, or already loaded — a no-op
        self.confirming_action = "load"
        self.confirming_entry = entry

    def _request_unload(self) -> None:
        if self.in_filter or self.confirming_action or not self.filtered:
            return
        entry = self.filtered[self.cursor]
        if not entry.can_load_unload or not entry.loaded:
            return  # can't unload this engine, or not loaded — a no-op
        self.confirming_action = "unload"
        self.confirming_entry = entry

    def _confirm_yes(self) -> None:
        if self.confirming_action is None or self.confirming_entry is None:
            return
        action = self.confirming_action
        entry = self.confirming_entry
        self.confirming_action = None
        self.confirming_entry = None
        self._start_action(entry, load=(action == "load"), exit_on_success=False)

    def _confirm_no(self) -> None:
        self.confirming_action = None
        self.confirming_entry = None

    def _on_escape(self) -> None:
        if self.side == "providers":
            self.notice = ""
            self.side = "models"
            return
        if not self._clear_filter():
            get_app().exit()

    def _on_key(self, data: str) -> None:
        key = latin_key(data)
        if key == "l":
            self._request_load()
        elif key == "u":
            self._request_unload()

    # ---------- provider field editing ----------

    def _start_field_edit(self) -> None:
        if not self.fields:
            return
        name, attr = self.fields[self.field_cursor]
        self.notice = ""
        self.editing = True
        # The url edits in place; the api key always starts blank — its
        # current value is never displayed, not even to edit.
        prefill = api_providers.section(self.session, name).url if attr == "url" else ""
        self.edit_buffer.document = Document(prefill, 0)

    def _finish_field_edit(self, *, save: bool) -> None:
        self.editing = False
        value = self.edit_buffer.text.strip()
        self.edit_buffer.reset()
        if not save:
            self.notice = "(cancelled)"
            return
        if not value:
            self.notice = "(empty — not saved)"
            return
        name, attr = self.fields[self.field_cursor]
        try:
            warning = api_providers.save_field(self.session, name, attr, value)  # type: ignore[arg-type]
        except Refused as e:
            self.notice = str(e)
            return
        if warning:
            # The registry took the value, the file did not — say so, or
            # the next launch silently forgets what the panel confirmed.
            self.notice = warning
        self._refresh_provider(name)

    def _set_field(self, text: str) -> None:
        """A paste onto a CLOSED field sets it outright: the field opens,
        becomes the clipboard, and is saved in the one gesture — a url or
        an api key is pasted whole, never composed, so there is nothing to
        position and nothing to confirm. Inside the editor a paste stays
        an ordinary paste: there the user IS composing."""
        if self.side != "providers" or self.editing or not text:
            return
        self._start_field_edit()
        if not self.editing:
            return  # nothing walkable under the cursor
        self.edit_buffer.document = Document(text, len(text))
        self._finish_field_edit(save=True)

    def _clear_field(self) -> None:
        """Delete on an api key field, outside the editor: forget the
        stored key — the config and the running session both."""
        if self.side != "providers":
            return
        name, attr = self.fields[self.field_cursor]
        if attr != "api_key":
            return
        if not api_providers.section(self.session, name).api_key:
            return  # nothing to clear — and no hint: the field is visibly bare
        warning = api_providers.clear_api_key(self.session, name)
        if warning:
            self.notice = warning
            return
        self._refresh_provider(name)  # the vanished (set) mark reports it

    def _fetch_rows(self, name: str) -> list[Provider]:
        """One provider's fresh listing, through the picker's one query —
        every OTHER configured provider skipped, so a catalog refresh
        never costs a sweep of dead engines."""
        skip = api_providers.configured(self.session) - {name}
        rows, reachable = api_providers.get_providers(self.session, skip=skip)
        if name in reachable:
            self.connected.add(name)
        else:
            self.connected.discard(name)
        return rows

    def _refresh_provider(self, name: str) -> None:
        """Re-list one provider after any of its settings changed, so the
        models side follows the edit without a relaunch — a provider that
        stopped answering simply loses its rows."""

        def worker() -> None:
            try:
                fetched = self._fetch_rows(name)
            except Exception:
                fetched = []  # the reread found nothing — honest emptiness
                self.connected.discard(name)
            rows = [
                ModelEntry(
                    full_spec=f"{name}/{model.name}",
                    provider_name=name,
                    model=model.name,
                    loaded=model.loaded if row.can_load_unload else True,
                    can_load_unload=row.can_load_unload,
                    size_bytes=model.size,
                    context=model.context,
                    cloud=not row.local,
                )
                for row in fetched
                for model in row.models
            ]
            # Concurrent refreshes (both catalogs at open, say) rebuild
            # the same list — the swap happens under the lock, so no
            # worker starts from a list another is replacing.
            with self._lock:
                entries = [e for e in self.all if e.provider_name != name]
                self.all = _ordered(entries + rows, self._order)
                self.pending.discard(name)
                self._refilter()
                # A remembered model whose rows just arrived gets the
                # cursor, unless the user already moved it somewhere.
                if self._initial_spec and self.cursor == 0:
                    for i, e in enumerate(self.filtered):
                        if e.full_spec == self._initial_spec:
                            self.cursor = i
                            break
            with contextlib.suppress(Exception):
                self.app.invalidate()

        threading.Thread(target=worker, daemon=True).start()

    # ---------- application wiring ----------

    def _build_app(self) -> Application[None]:
        kb = KeyBindings()

        idle = Condition(
            lambda: not self.busy and self.busy_error is None and self.confirming_action is None
        )
        confirming = Condition(lambda: self.confirming_action is not None)
        showing_error = Condition(lambda: self.busy_error is not None)

        # Dismiss any-key while the error dialog is up.
        @kb.add(Keys.Any, filter=showing_error, eager=True)
        def _dismiss_err(event: Any) -> None:
            self.busy_error = None

        # While the confirm dialog is up: only y/n/esc do anything.
        @kb.add("escape", eager=True, filter=confirming)
        def _confirm_esc(event: Any) -> None:
            self._confirm_no()

        @kb.add(Keys.Any, filter=confirming, eager=True)
        def _confirm_any(event: Any) -> None:
            key = latin_key(event.data) if event.data else ""
            if key == "y":
                self._confirm_yes()
            elif key == "n":
                self._confirm_no()

        self._standard_keys(kb, when=idle)

        @kb.add("tab", filter=idle)
        def _tab(event: Any) -> None:
            self._toggle_side()

        @kb.add("delete", filter=idle)
        def _clear(event: Any) -> None:
            self._clear_field()

        @kb.add("c-v", filter=idle)
        def _set_from_clipboard(event: Any) -> None:
            # One key from clipboard to configured: no Enter to open the
            # field, none to settle it.
            self._set_field(clipboard.paste())

        @kb.add(Keys.BracketedPaste, filter=idle)
        def _pasted(event: Any) -> None:
            # However the terminal chose to deliver it: many turn Ctrl+V
            # into a paste of their own rather than sending the control
            # byte, and then the app never sees `c-v` at all. On the
            # models side a paste is filter text, as it has always been.
            if self.side == "providers":
                self._set_field(clipboard.one_line(event.data))
            else:
                self._type(clipboard.one_line(event.data))

        # While a field is being edited, every binding above is suspended —
        # keystrokes belong to the inline editor. Ctrl+C stays live.
        editing = Condition(lambda: self.editing)
        edit_kb = KeyBindings()

        @edit_kb.add("enter", filter=editing)
        def _save(event: Any) -> None:
            self._finish_field_edit(save=True)

        @edit_kb.add("escape", filter=editing, eager=True)
        def _cancel(event: Any) -> None:
            self._finish_field_edit(save=False)

        @edit_kb.add("backspace", filter=editing)
        def _erase(event: Any) -> None:
            self.edit_buffer.delete_before_cursor(1)

        @edit_kb.add("delete", filter=editing)
        def _erase_ahead(event: Any) -> None:
            self.edit_buffer.delete(1)

        @edit_kb.add("left", filter=editing)
        def _left(event: Any) -> None:
            self.edit_buffer.cursor_position = max(0, self.edit_buffer.cursor_position - 1)

        @edit_kb.add("right", filter=editing)
        def _right(event: Any) -> None:
            buffer = self.edit_buffer
            buffer.cursor_position = min(len(buffer.text), buffer.cursor_position + 1)

        @edit_kb.add("home", filter=editing)
        @edit_kb.add("c-a", filter=editing)
        def _home(event: Any) -> None:
            self.edit_buffer.cursor_position = 0

        @edit_kb.add("end", filter=editing)
        @edit_kb.add("c-e", filter=editing)
        def _end(event: Any) -> None:
            self.edit_buffer.cursor_position = len(self.edit_buffer.text)

        @edit_kb.add("c-u", filter=editing)
        def _wipe(event: Any) -> None:
            self.edit_buffer.reset()

        # Inside the editor a paste is an ordinary paste — inserted at the
        # cursor, Enter still saves. Only a CLOSED field is set outright.
        @edit_kb.add(Keys.BracketedPaste, filter=editing)
        def _paste(event: Any) -> None:
            self.edit_buffer.insert_text(clipboard.one_line(event.data))

        @edit_kb.add("c-v", filter=editing)
        def _paste_key(event: Any) -> None:
            self.edit_buffer.insert_text(clipboard.paste())

        @edit_kb.add(Keys.Any, filter=editing)
        def _typed(event: Any) -> None:
            if event.data and event.data.isprintable():
                self.edit_buffer.insert_text(event.data)

        always_kb = KeyBindings()

        @always_kb.add("c-c")
        def _ctrlc(event: Any) -> None:
            self.result = None
            event.app.exit()

        bindings = merge_key_bindings([ConditionalKeyBindings(kb, ~editing), edit_kb, always_kb])

        items_window = Window(
            content=self._make_items_control(cursor_line=self._cursor_line),
            wrap_lines=False,
            always_hide_cursor=True,
            # The window spans its whole half, so its style paints every
            # cell the rows leave bare. It must be a class that carries no
            # ATTRIBUTE: a window's style is what its fragments build on,
            # and each of them overrides only the colors it names — a `dim`
            # here would grey out every row and caption in the pane.
            # Two lines of margin above the cursor: exactly the caption
            # and its blank, so a group's header scrolls into view when
            # the cursor stands on the group's first model.
            scroll_offsets=ScrollOffsets(top=2),
            style="class:row.plain",
        )

        # Bottom row: the filter input when filtering, otherwise the help
        # line. Same height in both states so the list above doesn't shift.
        bottom_row = VSplit(
            [
                text_line(self._filter_text, filter=Condition(lambda: self.in_filter)),
                text_line(
                    self._help_text,
                    style="class:help",
                    filter=Condition(lambda: not self.in_filter),
                ),
            ]
        )

        # This picker assembles its own left pane, so it records the
        # items window itself (see ListScreen._max_row_content_width).
        self._items_window = items_window
        left_pane = HSplit(
            [
                text_line(self._header_text, style="class:header"),
                Window(height=1, char=" ", always_hide_cursor=True),
                items_window,
                text_line(
                    lambda: [("class:notice", "  " + self.notice if self.notice else "")],
                    filter=Condition(lambda: bool(self.notice)),
                ),
                Window(height=1, char=" ", always_hide_cursor=True),
                bottom_row,
            ],
            width=D(weight=1),
        )

        # Named _preview_window so the base class's measured pane width
        # serves the field cells.
        self._preview_window = Window(
            FormattedTextControl(
                text=self._providers_text,
                get_cursor_position=lambda: Point(0, self._panel_cursor_line()),
                show_cursor=False,
            ),
            wrap_lines=True,
            always_hide_cursor=True,
            scroll_offsets=ScrollOffsets(top=2),  # caption + blank, as on the left
            style="class:preview.body",
        )
        provider_panel = bordered_box(
            self._preview_window, width=D(weight=1), style="class:preview.body"
        )

        busy_dialog = ConditionalContainer(
            content=bordered_box(
                FormattedTextControl(text=self._dialog_text, show_cursor=False),
                width=D(min=60, max=80, preferred=64),
                height=D.exact(9),
                style="class:dialog.body",
                border_style="class:dialog.border",
                wrap=False,  # truncate long model names instead of wrapping
            ),
            filter=Condition(lambda: self.busy or self.busy_error is not None),
        )

        confirm_dialog = ConditionalContainer(
            content=bordered_box(
                FormattedTextControl(text=self._confirm_text, show_cursor=False),
                width=D(min=60, max=80, preferred=64),
                height=D.exact(7),
                style="class:dialog.body",
                border_style="class:dialog.border",
                wrap=False,
            ),
            filter=confirming,
        )

        dialog = HSplit([busy_dialog, confirm_dialog])
        root = VSplit([left_pane, self._preview_gap(), provider_panel])
        return self._finish_app(root, bindings, _style(), floats=[dialog])


def _ordered(entries: list[ModelEntry], order: dict[str, int]) -> list[ModelEntry]:
    """Panel order: the engines as the provider panel lists them, any
    other configured provider after, by name; models keep their client
    order within a provider."""
    return sorted(
        entries,
        key=lambda e: (order.get(e.provider_name, len(order)), e.provider_name),
    )
