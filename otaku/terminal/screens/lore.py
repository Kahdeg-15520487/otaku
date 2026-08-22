"""The lore browser: scenes and cast as two lenses over one memory,
journal rows reachable through both, editing in place through
`backend.api.lore.edit` with a full view reload after every save.

Two lenses over the same memory, switched with Tab — the story in order
(scenes) and the story by who is in it (cast). A journal row is the
intersection of a scene and a character, so it is reachable through both
parents, and `→` pivots between them on the focused row: the same entry,
two doors.

Enter opens the item as a FIELD LIST — one row per editable text
(`LoreView.scene_fields` / `char_fields`; the view composes, the browser
renders) — and Enter on a field edits it IN PLACE: the right panel's
header stays put and the text below it becomes the edit buffer (Ctrl+S
saves, Esc cancels). Editable fields are the write-once primitives;
derivatives (the histories) are shown dim and never editable — the
backend refuses them, fix the inputs and the outputs follow. The store
writers carry the invalidation; the browser never calls a model.
"""

from typing import Any, Literal

from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import (
    ConditionalKeyBindings,
    KeyBindings,
    merge_key_bindings,
)
from prompt_toolkit.layout.containers import VSplit, Window
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.layout.dimension import D
from prompt_toolkit.styles import Style

from otaku.backend import Character, Scene
from otaku.backend.api import lore as api_lore
from otaku.backend.api.lore import Field, LoreView
from otaku.backend.session import Refused, Session
from otaku.formatting import flatten, truncate
from otaku.terminal.screens.base import (
    ListScreen,
    ansi_fragments,
    base_style,
    page_step,
    wrap_text,
)
from otaku.terminal.tty.theme import theme
from otaku.terminal.tty.typography import highlight_toml

Lens = Literal["scenes", "cast"]


def browse(session: Session, lens: Lens = "scenes") -> None:
    """Open the lore browser on the story — on the scenes lens (/lore) or
    the cast lens (/cast). Pure view/edit — nothing is returned; edits
    are written as they are saved."""
    _LoreBrowser(session, lens=lens).run()


def _style() -> Style:
    """Shared chrome from `base_style` plus this browser's row and preview
    overrides, in the shades the terminal background asked for."""
    colors = theme()
    panel = f"bg:{colors.panel.style}"
    return Style.from_dict(
        {
            **base_style(),
            "row": f"fg:{colors.text.style} {panel}",
            "row.selected": f"bold fg:{colors.ink.style} bg:{colors.selection.style}",
            "row.dim": f"dim fg:{colors.muted.style} {panel}",
            "row.dim.selected": f"dim fg:{colors.ink.style} bg:{colors.selection.style}",
            "preview.title": f"bold fg:{colors.title.style} {panel}",
            "preview.muted": f"dim fg:{colors.muted.style} {panel}",
            "preview.body": f"fg:{colors.text.style} {panel}",
            "notice": f"dim fg:{colors.muted.style} {panel}",
        }
    )


class _LoreBrowser(ListScreen):
    def __init__(self, session: Session, lens: Lens = "scenes") -> None:
        super().__init__()
        self.session = session
        self.view: LoreView = api_lore.view(session)

        self.lens: Lens = lens
        self.detail: tuple[str, int] | None = None  # ("scene", id) | ("char", id)
        self.fields: list[Field] = []
        self.scenes_f: list[int] = list(range(len(self.view.scenes)))
        self.cast_f: list[int] = list(range(len(self.view.cast)))
        # The base owns the ONE cursor; the other lens's position and the
        # list position under an open detail are stashed and restored.
        self._other_pos: int = 0
        self._list_pos: int = 0

        # Inline editing: while True the right panel is the edit buffer and
        # every navigation binding is suspended — keystrokes belong to it.
        self.editing: bool = False
        self.edit_buffer = Buffer(multiline=True)

        self.app = self._build_app()

    def run(self) -> None:
        self.app.run()

    # ---------- view lookups ----------

    def _reload(self) -> None:
        """The whole memory again, after a save — cheap for one story, and
        the store's own invalidation is never mirrored by hand. The
        visible set is NOT recomputed: an edit that drops a row out of an
        open filter would otherwise take it away as it is saved."""
        self.view = api_lore.view(self.session)
        self._rebuild_fields()

    def _scene_by_id(self, scene_id: int) -> Scene | None:
        return next((s for s in self.view.scenes if s.id == scene_id), None)

    def _char_by_id(self, cid: int) -> Character | None:
        return next((c for c in self.view.cast if c.id == cid), None)

    def _latest_state(self, cid: int) -> Field | None:
        """The character's newest state row, as their field list shows it."""
        states = [f for f in self.view.char_fields(cid) if f.kind == "state"]
        return states[-1] if states else None

    def _history_field(self, cid: int) -> Field | None:
        return next((f for f in self.view.char_fields(cid) if f.kind == "history"), None)

    def _label_parts(self, scene_id: int) -> tuple[str, str, str]:
        """`scene_label`'s "4  61-84  The Crossing" split back into
        (number, span, title) for the aligned list columns — the span is
        the one N-M part, so the parse cannot take a title for it."""
        parts = self.view.scene_label(scene_id).split("  ")
        no = parts[0]
        rest = parts[1:]
        span = ""
        if rest and _is_span(rest[0]):
            span, rest = rest[0], rest[1:]
        return no, span, "  ".join(rest)

    def _rebuild_fields(self) -> None:
        if self.detail is None:
            self.fields = []
            return
        kind, target = self.detail
        if kind == "scene":
            self.fields = self.view.scene_fields(target)
        else:
            self.fields = self.view.char_fields(target)
        if self.cursor >= len(self.fields):
            self.cursor = max(0, len(self.fields) - 1)

    # ---------- text content ----------

    def _header_text(self) -> StyleAndTextTuples:
        if self.detail is not None:
            kind, target = self.detail
            if kind == "scene":
                scene = self._scene_by_id(target)
                no = self._label_parts(target)[0]
                if scene is not None and scene.title:
                    return [("class:header", f" Scene {no}: {truncate(flatten(scene.title), 60)}")]
                return [("class:header", f" Scene {no}")]
            char = self._char_by_id(target)
            name = char.name if char else "?"
            aka = f" (aka {', '.join(char.aliases)})" if char and char.aliases else ""
            return [("class:header", f" {name}{aka}")]
        if self.lens == "scenes":
            return [("class:header", f" Scenes ({len(self.scenes_f)})")]
        return [("class:header", f" Cast ({len(self.cast_f)})")]

    def _items_text(self) -> StyleAndTextTuples:
        out: StyleAndTextTuples = []
        if self.detail is not None:
            if not self.fields:
                out.append(("class:muted", "  (nothing here yet)"))
                return out
            # The char view's journal rows carry their scene's number as its
            # own column, enumerated like the scenes list; rows without one
            # (description, history) keep the column blank.
            nos = [f.scene_no for f in self.fields if f.scene_no is not None]
            no_w = max((len(str(n)) for n in nos), default=0)
            label_w = min(24, max(len(f.label) for f in self.fields))
            avail = max(10, self._max_row_content_width() - 4 - no_w - 2 - label_w - 3)
            for i, f in enumerate(self.fields):
                head = truncate(flatten(f.text[: 4 * avail]), avail) or "(empty)"
                no = f"{f.scene_no:>{no_w}}  " if f.scene_no is not None else " " * (no_w + 2)
                row = f"{no if no_w else ''}{truncate(f.label, label_w):<{label_w}} · {head}"
                self._emit_row(out, i == self.cursor, row, dim=not f.editable)
            return out
        if self.lens == "scenes":
            if not self.scenes_f:
                msg = "(no matches)" if self.query else "(no scenes yet — they close as you play)"
                out.append(("class:muted", "  " + msg))
                return out
            parts = [self._label_parts(self.view.scenes[i].id) for i in self.scenes_f]
            no_w = max(len(no) for no, _, _ in parts)
            span_w = max(len(span) for _, span, _ in parts)
            # prefix(4) + no + "  " + span + "  " — the row's own spacing.
            avail = max(10, self._max_row_content_width() - 4 - no_w - 2 - span_w - 2)
            for row_i, (no, span, title) in enumerate(parts):
                row = f"{no:>{no_w}}  {span:>{span_w}}  {truncate(flatten(title), avail)}"
                self._emit_row(out, row_i == self.cursor, row)
            return out
        if not self.cast_f:
            msg = "(no matches)" if self.query else "(no characters yet)"
            out.append(("class:muted", "  " + msg))
            return out
        name_w = min(20, max(len(c.name) for c in self.view.cast))
        avail = max(10, self._max_row_content_width() - 4 - name_w - 3)
        for row_i, idx in enumerate(self.cast_f):
            c = self.view.cast[idx]
            latest = self._latest_state(c.id)
            snippet = f"now: {latest.text}" if latest else "(no journal yet)"
            row = f"{truncate(c.name, name_w):<{name_w}} · {truncate(flatten(snippet), avail)}"
            self._emit_row(out, row_i == self.cursor, row)
        return out

    def _panel_header_text(self) -> StyleAndTextTuples:
        """The fixed header above the focused field's text. It lives in its
        own window so it stays put when the text below it becomes the edit
        buffer — editing happens exactly where the text is displayed."""
        if self.detail is None or not self.fields:
            return [("", "")]
        return [("class:preview.title", self.fields[self.cursor].label + "\n")]

    def _preview_text(self) -> StyleAndTextTuples:
        width = max(10, self._preview_inner_width())
        out: StyleAndTextTuples = []

        if self.detail is not None:
            if not self.fields:
                return [("class:preview.muted", "nothing to preview")]
            f = self.fields[self.cursor]
            if f.kind == "card" and f.text:
                # The archive reads as TOML: keys and macros in the command
                # color — highlighted after the wrap, so the widths stay
                # honest (escapes take no columns the wrap could count).
                wrapped = "\n".join(wrap_text(f.text, width))
                for line in highlight_toml(wrapped).split("\n"):
                    out.extend(ansi_fragments(line, "class:preview.body"))
                    out.append(("class:preview.body", "\n"))
                return out
            for line in wrap_text(f.text or "(empty)", width):
                out.append(("class:preview.body", line + "\n"))
            return out

        if self.lens == "scenes":
            if not self.scenes_f:
                return [("class:preview.muted", "nothing to preview")]
            s = self.view.scenes[self.scenes_f[self.cursor]]
            no, span, title = self._label_parts(s.id)
            out.append(("class:preview.title", (flatten(title) or f"scene {no}") + "\n"))
            out.append(("class:preview.muted", f"messages {span}\n"))
            out.append(("class:preview.body", "\n"))
            for line in wrap_text(s.summary or "(no summary)", width):
                out.append(("class:preview.body", line + "\n"))
            present = [
                c.name
                for c in self.view.cast
                if any(j.scene_id == s.id and j.character_id == c.id for j in self.view.journals)
            ]
            if present:
                out.append(("class:preview.body", "\n"))
                out.append(("class:preview.muted", "present: " + ", ".join(present) + "\n"))
            return out

        if not self.cast_f:
            return [("class:preview.muted", "nothing to preview")]
        c = self.view.cast[self.cast_f[self.cursor]]
        aka = f" (aka {', '.join(c.aliases)})" if c.aliases else ""
        out.append(("class:preview.title", f"{c.name}{aka}\n"))
        if c.description:
            out.append(("class:preview.body", "\n"))
            for line in wrap_text(c.description, width):
                out.append(("class:preview.body", line + "\n"))
        latest = self._latest_state(c.id)
        if latest is not None:
            out.append(("class:preview.body", "\n"))
            out.append(("class:preview.muted", f"now ({self.view.vintage(latest.target)}):\n"))
            for line in wrap_text(latest.text, width):
                out.append(("class:preview.body", line + "\n"))
            history = self._history_field(c.id)
            if history is not None:
                out.append(("class:preview.body", "\n"))
                out.append(("class:preview.muted", "so far (rebuilt from entries):\n"))
                for line in wrap_text(history.text, width):
                    out.append(("class:preview.muted", line + "\n"))
        else:
            out.append(("class:preview.body", "\n"))
            out.append(("class:preview.muted", "(no journal yet)\n"))
        return out

    def _help_text(self) -> StyleAndTextTuples:
        if self.editing:
            return [("class:help", " editing — ctrl+s save · esc cancel")]
        if self.in_filter:
            return [
                (
                    "class:help",
                    " type to filter · ↑/↓ navigate · enter open · esc clear filter",
                )
            ]
        if self.detail is not None:
            other = "character" if self.detail[0] == "scene" else "scene"
            return [("class:help", f" ↑/↓ fields · enter edit · → their {other} · esc back")]
        other = "cast" if self.lens == "scenes" else "scenes"
        return [("class:help", f" ↑/↓ navigate · tab {other} · enter open · / filter · esc quit")]

    # ---------- behavior ----------

    def _rows_count(self) -> int:
        if self.detail is not None:
            return len(self.fields)
        return len(self.scenes_f) if self.lens == "scenes" else len(self.cast_f)

    def _move_cursor(self, delta: int) -> None:
        self.notice = ""
        super()._move_cursor(delta)

    def _refilter(self) -> None:
        q = self.query.strip().casefold()
        if not q:
            self.scenes_f = list(range(len(self.view.scenes)))
            self.cast_f = list(range(len(self.view.cast)))
        elif self.lens == "scenes":
            self.scenes_f = [
                i
                for i, s in enumerate(self.view.scenes)
                if q in f"{s.title} {s.summary}".casefold()
            ]
        else:
            self.cast_f = [
                i
                for i, c in enumerate(self.view.cast)
                if q
                in (
                    c.name
                    + " "
                    + " ".join(c.aliases)
                    + " "
                    + c.description
                    + " "
                    + (state.text if (state := self._latest_state(c.id)) else "")
                ).casefold()
            ]
        if self.cursor >= self._rows_count():
            self.cursor = max(0, self._rows_count() - 1)

    def _tab(self) -> None:
        self.notice = ""
        if self.detail is not None:
            return
        self.lens = "cast" if self.lens == "scenes" else "scenes"
        # Each lens keeps its own position; the base's one cursor swaps
        # with the stash on the way through.
        self.cursor, self._other_pos = self._other_pos, self.cursor
        if self.query:
            self._refilter()
        self.cursor = min(self.cursor, max(0, self._rows_count() - 1))

    def _open(self) -> None:
        self.notice = ""
        if self.detail is not None:
            return  # editing goes through _start_edit
        if self.lens == "scenes":
            if not self.scenes_f:
                return
            scene = self.view.scenes[self.scenes_f[self.cursor]]
            self.detail = ("scene", scene.id)
        else:
            if not self.cast_f:
                return
            char = self.view.cast[self.cast_f[self.cursor]]
            self.detail = ("char", char.id)
        self._list_pos = self.cursor
        self.cursor = 0
        self._rebuild_fields()

    def _pivot(self) -> None:
        """`→` on a journal field: the same row through the other lens."""
        self.notice = ""
        if self.detail is None or not self.fields:
            return
        f = self.fields[self.cursor]
        if f.pivot is None:
            return
        from_scene = self.detail[0] == "scene"
        self.detail = ("char", f.pivot) if from_scene else ("scene", f.pivot)
        self._rebuild_fields()
        # Land on the same journal row's same field, seen from the other side.
        for i, g in enumerate(self.fields):
            if g.kind == f.kind and g.target == f.target:
                self.cursor = i
                break
        else:
            self.cursor = 0

    def _on_enter(self) -> None:
        if self.detail is not None:
            self._start_edit()
        else:
            self._open()

    def _on_escape(self) -> None:
        self.notice = ""
        if self._clear_filter():
            return
        if self.detail is not None:
            self.detail = None
            self.fields = []
            self.cursor = min(self._list_pos, max(0, self._rows_count() - 1))
            return
        get_app().exit()

    def _type(self, data: str) -> None:
        """The base behavior, except that `/` opens the filter only on the
        top-level lists — a detail view has nothing to filter."""
        if self.in_filter:
            self.query += data
            self._refilter()
            return
        self.notice = ""
        if self.detail is None and data == "/":
            self._open_filter()

    # ---------- editing ----------

    def _edit_guard(self) -> str | None:
        """Why the focused field can't be edited, or None to go."""
        if self.detail is None or not self.fields:
            return "nothing to edit"
        f = self.fields[self.cursor]
        if not f.editable:
            if f.kind == "history":
                return "history is rebuilt from the entries — edit those instead"
            if f.kind == "state":
                return "only the latest state is ever read again"
            return "not editable"
        return None

    def _start_edit(self) -> None:
        """Enter on a field: the text under the header becomes the buffer."""
        reason = self._edit_guard()
        if reason is not None:
            self.notice = reason
            return
        f = self.fields[self.cursor]
        self.notice = ""
        self.editing = True
        # Cursor at the START: an edit begins by reading, and a long text
        # opened at its end shows only its tail.
        self.edit_buffer.document = Document(f.text, 0)
        self.app.layout.focus(self._edit_control)

    def _edit_width(self) -> int:
        """The edit window's rendered width — the wrap width the display
        actually uses; the layout math is the fallback before a render."""
        info = self._edit_window.render_info
        if info is not None and info.window_width > 0:
            return info.window_width
        return max(10, self._preview_inner_width())

    @staticmethod
    def _display_rows(text: str, width: int) -> list[tuple[int, int, bool]]:
        """(start, length, line_end) of each wrapped DISPLAY row — the same
        character wrapping the Window renders, so motion by row lands where
        the eye expects."""
        rows: list[tuple[int, int, bool]] = []
        pos = 0
        for line in text.split("\n"):
            start = 0
            while True:
                length = min(width, len(line) - start)
                line_end = start + length >= len(line)
                rows.append((pos + start, length, line_end))
                if line_end:
                    break
                start += length
            pos += len(line) + 1
        return rows

    def _move_edit_cursor(self, delta: int) -> None:
        """Up/down inside the editor move by display row, not logical line.
        Prose fields are one long wrapped line — the default logical-line
        motion has nowhere to go on them and the cursor just sticks."""
        rows = self._display_rows(self.edit_buffer.text, self._edit_width())
        cur = self.edit_buffer.cursor_position
        idx = len(rows) - 1
        for i, (start, length, line_end) in enumerate(rows):
            # On a wrapped (non-final) row the offset just past it already
            # displays at the start of the next row.
            if cur < start + length + (1 if line_end else 0):
                idx = i
                break
        target = max(0, min(len(rows) - 1, idx + delta))
        if target == idx:
            return
        col = cur - rows[idx][0]
        tstart, tlength, tline_end = rows[target]
        self.edit_buffer.cursor_position = tstart + min(
            col, tlength if tline_end else max(0, tlength - 1)
        )

    def _finish_edit(self, *, save: bool) -> None:
        """Ctrl+S applies the buffer through `api.lore.edit` and reloads
        the view; Esc discards it."""
        self.editing = False
        self.app.layout.focus(self._items_control)
        if not save:
            self.notice = "(cancelled)"
            return
        f = self.fields[self.cursor]
        new = self.edit_buffer.text.rstrip("\n")
        if new == f.text:
            self.notice = "(unchanged)"
            return
        try:
            api_lore.edit(self.session, f.kind, f.target, new)
        except Refused as e:
            self.notice = str(e)
            return
        self._reload()
        self.notice = "saved"

    # ---------- application wiring ----------

    def _build_app(self) -> Application[None]:
        kb = KeyBindings()
        self._standard_keys(kb)

        @kb.add("tab")
        def _tab_key(event: Any) -> None:
            self._tab()

        @kb.add("right")
        def _right(event: Any) -> None:
            self._pivot()

        # While the buffer owns the panel, every binding above is suspended —
        # keystrokes are the buffer's (the app's default bindings edit it).
        # Only save/cancel and quit stay live.
        editing = Condition(lambda: self.editing)
        edit_kb = KeyBindings()

        @edit_kb.add("c-s", filter=editing)
        def _save(event: Any) -> None:
            self._finish_edit(save=True)

        @edit_kb.add("escape", filter=editing, eager=True)
        def _cancel(event: Any) -> None:
            self._finish_edit(save=False)

        # The buffer's own bindings know arrows, not pages.
        @edit_kb.add("pageup", filter=editing)
        def _edit_pgup(event: Any) -> None:
            self.edit_buffer.cursor_up(page_step())

        @edit_kb.add("pagedown", filter=editing)
        def _edit_pgdn(event: Any) -> None:
            self.edit_buffer.cursor_down(page_step())

        always_kb = KeyBindings()

        @always_kb.add("c-c")
        def _ctrlc(event: Any) -> None:
            event.app.exit()

        bindings = merge_key_bindings([ConditionalKeyBindings(kb, ~editing), edit_kb, always_kb])

        # Focusable so focus has somewhere to return to when editing ends.
        self._items_control = self._make_items_control(focusable=True)
        items_window = Window(
            content=self._items_control,
            wrap_lines=False,
            always_hide_cursor=True,
            style="class:row",
        )
        left_pane = self._list_pane(items_window, width=D(weight=1), notice=True)

        # Motion inside the editor, attached to the control itself so it only
        # exists while the buffer has focus — and outranks the default
        # logical-line motion, which sticks on wrapped prose.
        edit_motion = KeyBindings()

        @edit_motion.add("up")
        def _edit_up(event: Any) -> None:
            self._move_edit_cursor(-1)

        @edit_motion.add("down")
        def _edit_down(event: Any) -> None:
            self._move_edit_cursor(1)

        self._edit_control = BufferControl(
            buffer=self.edit_buffer, focusable=True, key_bindings=edit_motion
        )
        self._edit_window = Window(self._edit_control, wrap_lines=True, style="class:preview.body")
        preview_pane = self._preview_panel(
            header_filter=Condition(lambda: self.detail is not None and bool(self.fields)),
            editing=editing,
            edit_window=self._edit_window,
        )

        root = VSplit([left_pane, self._preview_gap(), preview_pane])
        return self._finish_app(root, bindings, _style(), floats=[])


def _is_span(part: str) -> bool:
    """Whether a label part is the N-M span column."""
    first, dash, last = part.partition("-")
    return bool(dash) and first.isdigit() and last.isdigit()
