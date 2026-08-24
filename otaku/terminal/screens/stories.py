"""Story browser — opened by `/stories`.

A single full-screen Application with two views — the story list and a
message-by-message view of one story — switched internally so transitions
are flicker-free. Both views are the same list-plus-preview layout; only
the split changes.

  View 1 (story list) — list and preview share the width 50/50:
        Stories (N)                    │ ┌────────────────┐
        <blank>                        │ │  model name    │  bold, title
          > 05-02 16:55 · 6 msg · t…   │ │  Sat … · 2h ago│  muted
          ...                          │ │  arc text…     │
        <blank>                        │ │  first prompt: │  muted
        type to filter · ↑/↓ · …       │ │  prompt text…  │
                                       │ └────────────────┘

  View 2 (message list) — list gets 2/3, preview 1/3:
        Story: The Long Road · 12 messages           bold, title
        <blank>
          >  1. [user] I push the d…   │ ┌────────────┐
          ...                          │ │  1. user   │  the selected
        <blank>                        │ │  <content> │  message in full,
        ↑/↓ · enter resume · …         │ │  omlx/big  │  model dimmed,
                                       │ └────────────┘  right-aligned

A row's label is the story's title, else its newest story-so-far rollup,
else its first prompt. `/` filters; in the story list the filter also
matches full message content, indexed lazily on the first keystroke.
Enter drills in; Enter on the last message resumes, and on an earlier
one a dialog asks what resuming there means — fork from that point (the
default), truncate the story, or cancel. Every write — the settled land,
an edit, a delete — is EXECUTED inside the screen through
`backend.api.stories` (the screens' one ownership rule); the landing
line rides the result for the caller to print. `e` edits a message in
place; Del deletes a story after a confirm.
"""

from dataclasses import replace
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
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.containers import ConditionalContainer, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import D
from prompt_toolkit.styles import Style

from otaku.backend import Message, StoryListing
from otaku.backend.api import stories as api_stories
from otaku.backend.session import Refused, Session
from otaku.formatting import flatten, human_age, truncate
from otaku.terminal.screens.base import (
    ListScreen,
    ansi_fragments,
    base_style,
    bordered_box,
    page_step,
    wrap_text,
)
from otaku.terminal.tty import latin_key
from otaku.terminal.tty.render import message as render_message
from otaku.terminal.tty.theme import theme


def _style() -> Style:
    """Shared chrome from `base_style` plus the row and preview overrides
    this browser needs, in the shades the terminal background asked for."""
    colors = theme()
    panel = f"bg:{colors.panel.style}"
    return Style.from_dict(
        {
            **base_style(),
            "row": f"fg:{colors.text.style} {panel}",
            "row.selected": f"bold fg:{colors.ink.style} bg:{colors.selection.style}",
            "preview.title": f"bold fg:{colors.title.style} {panel}",
            "preview.muted": f"dim fg:{colors.muted.style} {panel}",
            "preview.body": f"fg:{colors.text.style} {panel}",
            "notice": f"dim fg:{colors.muted.style} {panel}",
        }
    )


# List-to-preview split, list:preview. The story list gets an even split so
# the preview has room for the arc; the message view gives the list twice the
# preview, since the rows carry the content and the preview only echoes one.
_STORY_SPLIT = (1, 1)
_TURN_SPLIT = (2, 1)

# The resume dialog's rows, in order: (action, label). The action is what
# the picker returns; "cancel" closes the dialog and stays in the browser.
_RESUME_OPTIONS: tuple[tuple[Literal["cancel"] | api_stories.LandAction, str], ...] = (
    ("fork", "Fork — continue in a new story from here"),
    ("truncate", "Truncate — discard the messages after this one"),
    ("cancel", "Cancel"),
)


class StoryPicker(ListScreen):
    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session
        # How a body looks — chat's one renderer, reached from below it.
        self._render = render_message
        rows = api_stories.listing(session)
        self.all: list[StoryListing] = list(rows)
        self.filtered: list[StoryListing] = list(rows)
        # in_filter/query are shared by both views; stash the story-list filter
        # while drilled into messages so returning restores it verbatim.
        self._story_filter: tuple[bool, str] = (False, "")
        if session.story_id is not None:
            for i, row in enumerate(self.all):
                if row.id == session.story_id:
                    self.cursor = i
                    break
        self._list_pos: int = self.cursor  # the story-list position, kept across a drill-in

        self.in_turns: bool = False
        self.selected_story: StoryListing | None = None
        self.loaded_msgs: list[Message] = []
        # Indices into loaded_msgs that match the message filter (all of them
        # when no query). turn_cursor indexes THIS list; resume maps back to
        # the original position so a filtered pick still truncates correctly.
        self.turn_filtered: list[int] = []
        self.turn_cursor: int = 0

        self.confirming_delete: bool = False

        # The resume dialog (Enter on an earlier message): up or not, and
        # which _RESUME_OPTIONS row is highlighted (fork is the default).
        self.confirming_resume: bool = False
        self.resume_choice: int = 0

        # Inline message editing (`e` in the message view): while True the
        # preview body is the edit buffer and navigation is suspended.
        self.editing: bool = False
        self.edit_buffer = Buffer(multiline=True)

        # The landing line api.stories.land answered; None until then.
        self.result: str | None = None
        self.app = self._build_app()

    def run(self) -> str | None:
        if not self.all:
            return None
        self.app.run()
        return self.result

    # ---------- text content for each pane ----------

    def _header_text(self) -> StyleAndTextTuples:
        if self.in_turns and self.selected_story is not None:
            row = self.selected_story
            story = truncate(flatten(row.label), 50)
            prefix = f" Story: {story}" if story else " Story"
            return [("class:header", f"{prefix} · {row.num_messages} messages")]
        n, total = len(self.filtered), len(self.all)
        label = f"Stories ({n} of {total})" if n != total else f"Stories ({n})"
        return [("class:header", " " + label)]

    def _confirm_text(self) -> StyleAndTextTuples:
        return [
            ("class:dialog.title", "Delete this story?\n"),
            ("class:dialog.body", "(its messages, scenes, and cast go with it)\n"),
            ("class:dialog.muted", "y to confirm     n / esc to cancel"),
        ]

    def _resume_text(self) -> StyleAndTextTuples:
        picked = self.turn_filtered[self.cursor] + 1 if self.turn_filtered else 0
        out: StyleAndTextTuples = [
            ("class:dialog.title", f"Resume at message {picked} of {len(self.loaded_msgs)}\n"),
            ("class:dialog.body", "\n"),
        ]
        for i, (_, label) in enumerate(_RESUME_OPTIONS):
            selected = i == self.resume_choice
            style = "class:row.selected" if selected else "class:dialog.body"
            out.append((style, f"{' > ' if selected else '   '}{label}\n"))
        out.append(("class:dialog.body", "\n"))
        out.append(("class:dialog.muted", "↑/↓ choose · enter confirm · esc cancel"))
        return out

    def _items_text(self) -> StyleAndTextTuples:
        out: StyleAndTextTuples = []
        if self.in_turns:
            if not self.loaded_msgs:
                out.append(("class:muted", "  (no messages)"))
                return out
            if not self.turn_filtered:
                out.append(("class:muted", "  (no matches)"))
                return out
            role_w = len("assistant")  # widest role name
            # prefix(4) + idx(4) + " · "(3) + role(role_w) + " · "(3) = fixed
            fixed = 4 + 4 + 3 + role_w + 3
            avail = max(10, self._max_row_content_width() - fixed)
            for row_i, orig in enumerate(self.turn_filtered):
                m = self.loaded_msgs[orig]
                # The list shows the line AS TYPED — the body is exactly
                # that, syntax included, so nothing is composed here. Slice
                # first: this renders per keystroke, and avail chars never
                # need more than a slice of a huge message.
                head = truncate(flatten(m.body[: 4 * avail]), avail) or "(empty)"
                # Styled AFTER the cut, so no escape can be sliced in half —
                # and on every row, selected or not: what a line says it is
                # does not depend on where the cursor happens to be.
                head = self._render(head, m.role)
                # The original message number, so a filtered row still reads
                # as its true position in the story.
                row = f"{orig + 1:>4} · {m.role:<{role_w}} · {head}"
                self._emit_row(out, row_i == self.cursor, row)
        else:
            if not self.filtered:
                msg = (
                    "(no matches)"
                    if self.query
                    else "(none yet — start chatting and they'll show up here)"
                )
                out.append(("class:muted", "  " + msg))
                return out
            avail = self._max_row_content_width() - 4 - len("MM-DD HH:MM ·    N msg · ")
            for i, listing in enumerate(self.filtered):
                ts = listing.updated_at.astimezone().strftime("%m-%d %H:%M")
                head = truncate(flatten(listing.label), max(10, avail))
                line = f"{ts} · {listing.num_messages:>4} msg · {head}"
                self._emit_row(out, i == self.cursor, line)
        return out

    def _panel_header_text(self) -> StyleAndTextTuples:
        """The fixed header above the message text — its own window, so it
        stays put when the text below it becomes the edit buffer."""
        if not self.in_turns or not self.turn_filtered:
            return [("", "")]
        orig = self.turn_filtered[self.cursor]
        return [("class:preview.title", f"{orig + 1}. {self.loaded_msgs[orig].role}\n")]

    def _preview_text(self) -> StyleAndTextTuples:
        width = max(10, self._preview_inner_width())

        if self.in_turns:
            if not self.turn_filtered:
                return [("class:preview.muted", "nothing to preview")]
            orig = self.turn_filtered[self.cursor]
            m = self.loaded_msgs[orig]
            out: StyleAndTextTuples = []
            if m.body:
                # Whatever `render` makes of it, parsed into fragments so
                # the window's own wrapping carries styles across wrapped
                # rows. Editing swaps this window out, so the buffer stays
                # raw text.
                body = self._render(m.body, m.role)
                if not body.endswith("\n"):
                    body += "\n"
                out.extend(ansi_fragments(body, "class:preview.body"))
            # The template snapshot shown DIM after a blank line — the
            # template layer (its `{body}` placeholder and all) that the turn
            # was played with, which the body alone does not show. It is not
            # what the model reads; `/context` shows that.
            if m.template:
                if m.body:
                    out.append(("class:preview.body", "\n"))
                for line in wrap_text(m.template, width):
                    out.append(("class:preview.muted", line + "\n"))
            # The model that generated THIS turn, dimmed and right-aligned —
            # user turns have none (messages.model is NULL there) and show
            # nothing.
            if m.role == "assistant" and m.model:
                label = f"{m.provider}/{m.model}" if m.provider else m.model
                out.append(("class:preview.body", "\n"))
                out.append(("class:preview.muted", label.rjust(width) + "\n"))
            return out

        if not self.filtered:
            return [("class:preview.muted", "nothing to preview")]
        row = self.filtered[self.cursor]
        out = [
            ("class:preview.title", (row.model or "?") + "\n"),
            ("class:preview.body", "\n"),
            (
                "class:preview.muted",
                row.updated_at.astimezone().strftime("%a %Y-%m-%d %H:%M")
                + " · "
                + human_age(row.updated_at)
                + "\n",
            ),
        ]
        # Title (if any) before the arc, each block separated by a blank
        # line; a story with neither simply shows nothing there.
        if row.title:
            out.append(("class:preview.body", "\n"))
            for line in wrap_text(flatten(row.title), width):
                out.append(("class:preview.title", line + "\n"))
        if row.story_so_far:
            out.append(("class:preview.body", "\n"))
            for line in wrap_text(row.story_so_far, width):
                out.append(("class:preview.body", line + "\n"))
        if row.first_user:
            out.append(("class:preview.body", "\n"))
            out.append(("class:preview.muted", "first prompt:\n"))
            for line in wrap_text(flatten(row.first_user), width):
                out.append(("class:preview.body", line + "\n"))
        return out

    def _help_text(self) -> StyleAndTextTuples:
        if self.editing:
            return [("class:help", " editing — ctrl+s save · esc cancel")]
        if self.in_filter:
            action = "enter resume" if self.in_turns else "enter drill in"
            return [
                (
                    "class:help",
                    f" type to filter · ↑/↓ navigate · {action} · esc clear filter",
                )
            ]
        if self.in_turns:
            return [
                (
                    "class:help",
                    " ↑/↓ navigate · / filter · e edit · enter resume from this turn · esc back",
                )
            ]
        return [
            (
                "class:help",
                " ↑/↓ navigate · / filter · enter drill in · del delete · esc quit",
            )
        ]

    # ---------- behavior ----------

    def _split(self) -> tuple[int, int]:
        """(left weight, preview weight) for the current view."""
        return _TURN_SPLIT if self.in_turns else _STORY_SPLIT

    def _refilter(self) -> None:
        if self.in_turns:
            self._refilter_turns()
            return
        q = self.query.strip().lower()
        if not q:
            self.filtered = list(self.all)
        else:
            # The whole filter rule lives below both frontends
            # (api.stories.search): buried content OR the row's own
            # face — so this browser and the page can never find
            # different stories. Cheap per keystroke (the content index
            # is session-held), and the corpus never crosses the
            # boundary.
            found = set(api_stories.search(self.session, q))
            self.filtered = [row for row in self.all if row.id in found]
        if self.cursor >= len(self.filtered):
            self.cursor = max(0, len(self.filtered) - 1)

    def _refilter_turns(self) -> None:
        q = self.query.strip().lower()
        if not q:
            self.turn_filtered = list(range(len(self.loaded_msgs)))
        else:
            self.turn_filtered = [i for i, m in enumerate(self.loaded_msgs) if q in m.body.lower()]
        if self.cursor >= len(self.turn_filtered):
            self.cursor = max(0, len(self.turn_filtered) - 1)

    def _rows_count(self) -> int:
        return len(self.turn_filtered) if self.in_turns else len(self.filtered)

    def _move_cursor(self, delta: int) -> None:
        self.notice = ""
        super()._move_cursor(delta)

    def _request_delete(self) -> None:
        if self.in_turns or self.confirming_delete or not self.filtered:
            return
        self.confirming_delete = True

    def _do_delete(self) -> None:
        if not self.filtered:
            self.confirming_delete = False
            return
        target = self.filtered[self.cursor]
        try:
            api_stories.delete(self.session, target.id)
        except Exception:
            # Silent failure is acceptable here — the row stays visible
            # and the user can try again or check the DB out of band.
            self.confirming_delete = False
            return
        self.all = [row for row in self.all if row.id != target.id]
        self._refilter()
        self.confirming_delete = False

    def _do_resume(self) -> None:
        action = _RESUME_OPTIONS[self.resume_choice][0]
        self.confirming_resume = False
        if action == "cancel" or self.selected_story is None or not self.turn_filtered:
            return
        self._land(action)

    def _land(self, action: api_stories.LandAction) -> None:
        """Execute the settled pick (the screens' one ownership rule) and
        leave with the landing line for the caller to print."""
        assert self.selected_story is not None
        upto = self.loaded_msgs[self.turn_filtered[self.cursor]]
        try:
            self.result = api_stories.land(self.session, self.selected_story.id, upto.id, action)
        except Refused as e:
            self.notice = str(e)
            return
        get_app().exit()

    def _on_enter(self) -> None:
        if self.in_turns:
            if not self.turn_filtered or self.selected_story is None:
                return
            orig = self.turn_filtered[self.cursor]
            if orig + 1 == len(self.loaded_msgs):
                self._land("resume")
            else:
                # An earlier turn: what resuming there means is the resume
                # dialog's question, fork being the default.
                self.confirming_resume = True
                self.resume_choice = 0
            return

        if not self.filtered:
            return
        self._list_pos = self.cursor
        self.selected_story = self.filtered[self.cursor]
        try:
            self.loaded_msgs = api_stories.messages_of(self.session, self.selected_story.id)
        except Exception:
            self.loaded_msgs = []
        # Fresh view: stash the story-list filter and start unfiltered on the
        # tail. Escape restores it verbatim on the way back.
        self._story_filter = (self.in_filter, self.query)
        self.in_filter = False
        self.query = ""
        self.turn_filtered = list(range(len(self.loaded_msgs)))
        self.cursor = max(0, len(self.turn_filtered) - 1)
        self.in_turns = True

    def _on_escape(self) -> None:
        self.notice = ""
        # In either view an active filter clears first; a second Esc backs out.
        if self._clear_filter():
            return
        if self.in_turns:
            self.in_turns = False
            self.loaded_msgs = []
            self.turn_filtered = []
            self.selected_story = None
            self.in_filter, self.query = self._story_filter
            self.cursor = self._list_pos
            return
        get_app().exit()

    def _on_key(self, data: str) -> None:
        if latin_key(data) == "e" and self.in_turns:
            self._start_edit()

    # ---------- inline message editing ----------

    def _start_edit(self) -> None:
        """`e` on a message: the text under the header becomes the buffer."""
        if not self.in_turns or not self.turn_filtered:
            self.notice = "nothing to edit"
            return
        orig = self.turn_filtered[self.cursor]
        text = self.loaded_msgs[orig].body
        self.notice = ""
        self.editing = True
        # Cursor at the START: an edit begins by reading, and a long text
        # opened at its end shows only its tail.
        self.edit_buffer.document = Document(text, 0)
        self.app.layout.focus(self._edit_control)

    def _finish_edit(self, *, save: bool) -> None:
        """Ctrl+S writes the corrected text; Esc discards it."""
        self.editing = False
        self.app.layout.focus(self._items_control)
        if not save:
            self.notice = "(cancelled)"
            return
        orig = self.turn_filtered[self.cursor]
        m = self.loaded_msgs[orig]
        new = self.edit_buffer.text.rstrip("\n")
        if new == m.body:
            self.notice = "(unchanged)"
            return
        try:
            api_stories.edit_message(self.session, m.id, new)
        except Refused as e:
            self.notice = str(e)
            return
        except Exception as e:
            self.notice = f"save failed: {e}"
            return
        self.loaded_msgs[orig] = replace(m, body=new)
        self.notice = "saved"

    # ---------- application wiring ----------

    def _build_app(self) -> Application[None]:
        kb = KeyBindings()
        confirming = Condition(lambda: self.confirming_delete)
        resuming = Condition(lambda: self.confirming_resume)

        # While the confirm dialog is up: only y/n/esc do anything.
        @kb.add("escape", eager=True, filter=confirming)
        def _confirm_esc(event: Any) -> None:
            self.confirming_delete = False

        @kb.add(Keys.Any, filter=confirming, eager=True)
        def _confirm_any(event: Any) -> None:
            key = latin_key(event.data) if event.data else ""
            if key == "y":
                self._do_delete()
            elif key == "n":
                self.confirming_delete = False

        # While the resume dialog is up: arrows walk the options, Enter
        # confirms the highlighted one, Esc closes back into the browser.
        @kb.add("escape", eager=True, filter=resuming)
        def _resume_esc(event: Any) -> None:
            self.confirming_resume = False

        @kb.add("up", filter=resuming)
        def _resume_up(event: Any) -> None:
            self.resume_choice = (self.resume_choice - 1) % len(_RESUME_OPTIONS)

        @kb.add("down", filter=resuming)
        def _resume_down(event: Any) -> None:
            self.resume_choice = (self.resume_choice + 1) % len(_RESUME_OPTIONS)

        @kb.add("enter", filter=resuming)
        def _resume_enter(event: Any) -> None:
            self._do_resume()

        idle = ~confirming & ~resuming
        self._standard_keys(kb, when=idle)

        @kb.add("delete")
        def _delete_key(event: Any) -> None:
            self._request_delete()

        # The key macOS captions "delete" arrives as backspace. Honor the
        # caption wherever no filter is open for backspace to edit — added
        # after the standard keys, so it outranks their no-op exactly there.
        @kb.add("backspace", filter=idle & Condition(lambda: not self.in_filter))
        def _delete_backspace(event: Any) -> None:
            self._request_delete()

        # While the buffer owns the panel, every binding above is suspended —
        # keystrokes belong to it. Only save/cancel and quit stay live.
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
            self.result = None
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
        # The left pane's width is a weighted share against the preview's —
        # 50/50 in the story list, 2:1 in the message view (re-evaluated
        # each render, so the split flips when the view does).
        left_pane = self._list_pane(
            items_window, width=lambda: D(weight=self._split()[0]), notice=True
        )

        self._edit_control = BufferControl(buffer=self.edit_buffer, focusable=True)
        preview_pane = self._preview_panel(
            header_filter=Condition(lambda: self.in_turns and bool(self.turn_filtered)),
            editing=editing,
            edit_window=Window(self._edit_control, wrap_lines=True, style="class:preview.body"),
        )

        confirm_dialog = ConditionalContainer(
            content=bordered_box(
                FormattedTextControl(text=self._confirm_text, show_cursor=False),
                width=D(min=44, max=70, preferred=60),
                height=D.exact(7),
                style="class:dialog.body",
                border_style="class:dialog.border",
            ),
            filter=confirming,
        )
        resume_dialog = ConditionalContainer(
            content=bordered_box(
                FormattedTextControl(text=self._resume_text, show_cursor=False),
                width=D(min=50, max=74, preferred=64),
                height=D.exact(11),
                style="class:dialog.body",
                border_style="class:dialog.border",
            ),
            filter=resuming,
        )

        root = VSplit([left_pane, self._preview_gap(), preview_pane])
        return self._finish_app(root, bindings, _style(), floats=[confirm_dialog, resume_dialog])


def pick(session: Session) -> str | None:
    """Browse; on a confirmed selection the land is EXECUTED and its
    landing line returned for the caller to print (with the scene
    re-echo); None when cancelled (Esc/Ctrl+C) — the loaded story is
    pre-selected."""
    return StoryPicker(session).run()
