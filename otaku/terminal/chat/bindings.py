"""The ONE binding module: the shared command table wired to the
terminal.

OPERATION-kind rows are wired generically: `OPERATIONS` maps their
tokens onto typed adapters `(session, raw) -> str` over the backend
calls — the sentence goes through `chat.say`, Refused is caught the same
way, and the dict's type holds the contract. INTERACTIVE rows get a
handler each: thin sequences of prompts, screens, waits, and ledger
choreography around backend calls, taking `chat` alone (the session
rides on it). The shortcut table carries both spellings of each key —
the binding form and the caption — so no seam translates by hand.
"""

import shutil
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import click

from otaku.backend import commands
from otaku.backend.api import cards as api_cards
from otaku.backend.api import lore as api_lore
from otaku.backend.api import play as api_play
from otaku.backend.api import providers as api_providers
from otaku.backend.api import reports as api_reports
from otaku.backend.api import settings as api_settings
from otaku.backend.api import stories as api_stories
from otaku.backend.api import transfer as api_transfer
from otaku.backend.api.lore import WorkerRun
from otaku.backend.session import Refused, Session
from otaku.terminal.chat import stream
from otaku.terminal.chat.chat import RESUME_TURNS, Chat
from otaku.terminal.screens import lore as screen_lore
from otaku.terminal.screens import models as screen_models
from otaku.terminal.screens import stories as screen_stories
from otaku.terminal.tty import BOLD, DIM, ERASE_LINE, RESET, YES_ANSWERS, error_line, latin_key
from otaku.terminal.tty.render import command_tokens, last_turns, message
from otaku.terminal.tty.typography import highlight_commands

# One OPERATION command: the raw argument text in, the sentence out.
Operation = Callable[[Session, str], str]

# token → backend call, for every OPERATION row of the shared table;
# built in one place so a new operation command is a table row + an
# entry here. `/new` is the one OPERATION with a handler instead (below):
# it swaps the story under the screen, and that break must be DRAWN —
# presentation the generic wiring has no business knowing.
OPERATIONS: dict[str, Operation] = {
    "/fork": api_stories.fork,
    "/title": api_stories.set_title,
    "/merge": api_lore.merge,
    "/usage": api_reports.usage,
    "/balance": lambda session, raw: api_reports.balances(session),
    "/info": lambda session, raw: api_reports.info(session),
    "/set think": api_settings.set_think,
    "/set parameter": api_settings.set_parameter,
    "/set verbose": api_settings.set_verbose,
    "/set autocorrect": api_settings.set_autocorrect,
}


class Shortcut(NamedTuple):
    """One key in both spellings: what prompt_toolkit binds and what the
    menus print."""

    key: str  # prompt_toolkit's name ("c-r")
    caption: str  # the human's ("Ctrl+R")


# The terminal's shortcut keys, by the token they run.
SHORTCUTS: dict[str, Shortcut] = {
    "/regen": Shortcut("c-r", "Ctrl+R"),
    "/undo": Shortcut("c-u", "Ctrl+U"),
    "/stories": Shortcut("c-t", "Ctrl+T"),
    "/lore": Shortcut("c-l", "Ctrl+L"),
    "/model": Shortcut("c-o", "Ctrl+O"),  # Ctrl+M is unusable — the terminal sends it as Enter
    "/bye": Shortcut("c-d", "Ctrl+D"),
}

# The commands that manage the screen ledger themselves (they take an
# exchange back, or echo their own block). Every other command's output
# lands below the last exchange and invalidates on its first say — the
# dispatch window watches for the write rather than assuming one, so a
# picker left without a choice costs the exchanges above it nothing.
_PLAYING = {"/undo", "/regen", "/card"}

# The keys-at-the-prompt rows of the terminal's own /help section.
# fmt: off
_KEY_ROWS: tuple[tuple[str, str], ...] = (
    ('"""', 'Begin a multiline message; close it with """'),
    ("@", "In a FILE argument: enable path autocompletion"),
    ("Up / Down", "Walk your recent prompt history"),
    ("Ctrl+C", "Clear the current line; cancel an in-flight reply"),
)
# fmt: on


def dispatch(chat: Chat, line: str) -> bool:
    """True when the line was a command (handled); False when it should
    play as story. Unknown /words are reported here; the argument text
    passes raw — semantic parsing is the backend's."""
    if not commands.is_command(line):
        return False
    spec = commands.find(line)
    token = spec.token if spec else line.split()[0]
    with chat.ledger.command_output(manages_screen=token in _PLAYING):
        try:
            if spec is None:
                chat.say(_unknown(line))
            elif spec.token in _INTERACTIVE:
                _INTERACTIVE[spec.token](chat, _argument(line, spec.token))
            else:
                chat.say(OPERATIONS[spec.token](chat.session, _argument(line, spec.token)))
        except Refused as e:
            chat.say(str(e))
    return True


def help_text(width: int | None = None) -> str:
    """The shared table's help, spelled for a terminal: the shortcut
    column the shared `help_text` has no room for, the argument shapes a
    narrow command column cannot afford (`_HELP_SPELLINGS`), and a
    layout that fits the screen — TWO columns when both hold a readable
    description, one otherwise. A description wraps inside its own
    column, its continuation under it, so no row is ever cut. `width`
    stands in for the measured terminal."""
    columns = shutil.get_terminal_size().columns if width is None else width
    blocks = _help_blocks()
    stacked = _help_stacked(_help_render(blocks, columns))
    half = (columns - _HELP_GAP) // 2
    if half - _help_widths(blocks)[2] < _HELP_MIN_DESCRIPTION:
        return "\n".join(stacked)
    cut = _help_cut(_help_render(blocks, half))
    left = _help_stacked(_help_render(blocks[:cut], half))
    right = _help_stacked(_help_render(blocks[cut:], half))
    beside = _help_beside(left, right)
    # Two columns only where they actually save height: halving the
    # description width costs wrapped lines, and just above the floor
    # that costs back everything the split saves.
    if len(beside.splitlines()) > len(stacked) * (1 - _HELP_TWO_COLUMN_SAVING):
        return "\n".join(stacked)
    return beside


# The terminal spells a few rows shorter than the shared table does: its
# command column is narrow where a web page's is not, so an argument
# shape that costs more than it explains is dropped here — and where
# dropping it would lose something, the description picks it up. The
# TABLE is untouched: this is one frontend's spelling, not the command.
_HELP_SPELLINGS: dict[str, tuple[str, str]] = {
    "/model": ("[SPEC]", "Switch model — SPEC is PROVIDER/MODEL; bare opens the picker"),
    "/set parameter": ("", ""),
    "/set verbose": ("", ""),
    "/set autocorrect": ("", ""),
}

_HELP_GAP = 5  # columns between the two help columns
_HELP_INDENT = 2
_HELP_KEY_GAP = 2  # between the command column and the shortcut column
# A description column narrower than this reads worse than a tall
# single column, so the second column is not worth taking.
_HELP_MIN_DESCRIPTION = 26
# Nor is it worth taking for a sliver: the split must save at least this
# share of the height to be worth the wrapping it forces.
_HELP_TWO_COLUMN_SAVING = 0.1

# One help block: its heading ("" for a group that names itself) and its
# rows, each a (label, shortcut caption, description).
_HelpBlock = tuple[str, list[tuple[str, str, str]]]


def _help_blocks() -> list[_HelpBlock]:
    """The help's groups in the table's order, the terminal's own
    spellings applied, with the keys section last."""
    blocks: list[_HelpBlock] = []
    group = None
    for spec in commands.COMMANDS:
        if spec.group != group:
            group = spec.group
            blocks.append((_GROUP_HEADINGS[group], []))
            if group == "playing":
                blocks[-1][1].append(("PROMPT", "", commands.PROSE_DESCRIPTION))
        args, description = spec.args, spec.description
        if spec.token in _HELP_SPELLINGS:
            args, replacement = _HELP_SPELLINGS[spec.token]
            description = replacement or description
        caption = SHORTCUTS[spec.token].caption if spec.token in SHORTCUTS else ""
        blocks[-1][1].append((f"{spec.token} {args}".strip(), caption, description))
    blocks.append(("Keys at the prompt:", [(key, "", text) for key, text in _KEY_ROWS]))
    return blocks


def _help_widths(blocks: list[_HelpBlock]) -> tuple[int, int, int]:
    """The command column, the shortcut column, and the two plus their
    padding — where a row's description begins."""
    rows = [row for _, block_rows in blocks for row in block_rows]
    label = max((len(label) for label, _, _ in rows), default=0)
    key = max((len(caption) for _, caption, _ in rows), default=0)
    return label, key, _HELP_INDENT + label + _HELP_KEY_GAP + key + 2


def _help_render(blocks: list[_HelpBlock], width: int) -> list[list[str]]:
    """Each block's lines at `width` columns — its own columns measured
    over these blocks alone, so a column packs to what it actually
    holds."""
    label_width, key_width, head = _help_widths(blocks)
    description_width = max(_HELP_MIN_DESCRIPTION, width - head)
    rendered = []
    for heading, rows in blocks:
        lines = [heading] if heading else []
        for label, caption, description in rows:
            lead = (
                f"{'':<{_HELP_INDENT}}{label:<{label_width}}"
                f"{'':<{_HELP_KEY_GAP}}{caption:<{key_width}}  "
            )
            # Never at a hyphen: "mid-stream" and "in-flight" are words,
            # and a column is no reason to break one. A token too long
            # for the column still breaks — the layout's width is a
            # promise, and a value list is the only thing that long.
            wrapped = textwrap.wrap(description, description_width, break_on_hyphens=False) or [""]
            lines.append((lead + wrapped[0]).rstrip())
            lines.extend((" " * len(lead) + more).rstrip() for more in wrapped[1:])
        rendered.append(lines)
    return rendered


def _help_stacked(rendered: list[list[str]]) -> list[str]:
    """The blocks down one column, a blank line between them."""
    lines: list[str] = []
    for block in rendered:
        if lines:
            lines.append("")
        lines += block
    return lines


def _help_cut(rendered: list[list[str]]) -> int:
    """The block the second column starts at — the split that leaves the
    two nearest to equal height. A group is never broken across them,
    and the first block always stays left."""
    heights = [len(block) + 1 for block in rendered]
    half = (sum(heights) + 1) // 2
    taken = 0
    for i, height in enumerate(heights):
        if i and taken + height > half:
            return i
        taken += height
    return len(rendered)


def _help_beside(left: list[str], right: list[str]) -> str:
    """Two columns side by side, the shorter one running out first."""
    width = max((len(line) for line in left), default=0)
    rows = []
    for i in range(max(len(left), len(right))):
        start = left[i] if i < len(left) else ""
        end = right[i] if i < len(right) else ""
        rows.append(f"{start:<{width}}{' ' * _HELP_GAP}{end}".rstrip())
    return "\n".join(rows)


# The /help group headings, matching the shared table's groups; "" for a
# separated group without a heading (meta: /help and /bye explain
# themselves).
_GROUP_HEADINGS = {
    "playing": "Playing:",
    "inline": "Inside a prompt:",
    "stories": "Stories:",
    "lore": "Lore:",
    "inspect": "Inspect:",
    "transfer": "Import/export:",
    "settings": "Model and settings:",
    "meta": "",
}


# ---------- the interactive handlers (one per INTERACTIVE row) ----------


def _undo(chat: Chat, raw: str) -> None:
    """Erase the exchange in place when the ledger proves it; report the
    new ending otherwise. The re-echoed turns below a report are turns —
    the next /undo or /regen works them — and taking them takes the
    report too, a fresh one printing in its place: the screen always
    shows one, current, report."""
    popped = api_play.undo(chat.session)
    if not popped:
        chat.ledger.invalidate()
        chat.say("Nothing to undo.")
        return
    refreshing = chat.ledger.top_is_report()
    if chat.ledger.erase_exchange():
        if refreshing:
            _report_undo_ending(chat)
        return  # otherwise the ending is still on screen — say nothing
    chat.ledger.invalidate()
    _report_undo_ending(chat)


def _report_undo_ending(chat: Chat) -> None:
    """The story's new ending, reported and re-echoed — and handed back
    to the ledger, the report line included, so the next /undo or /regen
    works the re-echoed turns."""
    chat.ledger.rule()
    if not chat.session.messages:
        chat.say("Undone. The story is now empty (its turns stay in the tree).")
        return
    report = f"{DIM}[ undone. the story now ends with: ]{RESET}"
    chat.say(f"{report}\n\n{last_turns(list(chat.session.messages), 2)}")
    chat.restore_tail(2, above=report)


def _regen(chat: Chat, raw: str) -> None:
    """Re-run the last prompt: the current reply becomes a sibling and a
    fresh one streams — in the old one's place when the screen allows;
    when it is beyond reach, the marker announces and the prompt being
    re-run echoes under it, so the new take reads as an exchange and
    /undo and /regen keep working it."""
    session = chat.session
    try:
        events = api_play.regenerate(session)
    except Refused as e:
        chat.ledger.invalidate()
        chat.say(str(e))
        return
    # The prompt the take re-runs, read BEFORE the stream starts (the
    # generator drops the standing reply on its first pull): the last
    # user row once the trailing reply goes — absent when the story is a
    # promptless reply, which regenerates on its own.
    msgs = list(session.messages)
    if msgs and msgs[-1].role == "assistant":
        msgs.pop()
    prompt = msgs[-1] if msgs else None
    if not chat.ledger.erase_reply():
        chat.ledger.invalidate()
        chat.ledger.rule()
        marker = f"{DIM}[ regenerating ]{RESET}"
        chat.say(marker)
        # The typed line stays above the marker — nothing of it to erase.
        chat.ledger.typed_gone()
        chat.ledger.echo_block(message(prompt.body, "user") if prompt else "", above=marker)
    while stream.show(chat, events):
        events = api_play.regenerate(session)


def _last(chat: Chat, raw: str) -> None:
    """`/last [N]` — show the last N turns again (default 5), the way a
    relaunch shows the scene: a clean view after undos, regens, etc."""
    argument = raw.strip()
    if argument and not (argument.isdigit() and int(argument) > 0):
        chat.say("Usage: /last [N]")
        return
    count = int(argument) if argument else _LAST_TURNS_DEFAULT
    session = chat.session
    if not session.messages:
        chat.say("No turns yet.")
        return
    rows = count * 2  # a turn is an exchange: the prompt and its reply
    chat.ledger.rule()
    # What the echo actually holds, never what was asked for: a short
    # story shows everything it has, and the report must not over-claim.
    shown = (len(list(session.messages)[-rows:]) + 1) // 2
    report = f"The last {shown} turns of this story:"
    chat.say(f"{report}\n\n{last_turns(list(session.messages), rows)}")
    chat.restore_tail(rows, above=report)


# Turns /last shows when called bare — a turn being an exchange, the
# prompt and its reply (two message rows).
_LAST_TURNS_DEFAULT = 5


def _clear(chat: Chat, raw: str) -> None:
    """Wipe the screen; the story is untouched and /last brings the
    scene back. The next prompt opens at the top."""
    chat.ledger.clear()


def _system(chat: Chat, raw: str) -> None:
    """The terminal's file affordance: an argument naming a readable file
    (a leading `@` stripped) becomes the prompt's text; then ONE backend
    call — api.stories.set_system(text)."""
    text = raw.strip().removeprefix("@")
    path = _existing_file(text) if text else None
    if path is not None:
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError as e:
            chat.say(error_line(f"Could not read {path}: {e}"))
            return
        if not text:
            chat.say(f"{path} is empty — system prompt unchanged.")
            return
    chat.say(api_stories.set_system(chat.session, text))


def _stories(chat: Chat, raw: str) -> None:
    """Browse every story, preview its turns, resume anywhere — the
    screen executes what its selection settled and returns the landing
    line; landing echoes the scene under the break rule."""
    if not api_stories.listing(chat.session):
        chat.say("No saved stories yet.")
        return
    landed = screen_stories.pick(chat.session)
    if landed is None:
        return  # cancelled — the screen restored itself; nothing moved
    chat.ledger.rule()
    chat.say(f"{landed}\n\n{last_turns(list(chat.session.messages), RESUME_TURNS)}")
    chat.restore_tail(RESUME_TURNS)


def _new(chat: Chat, raw: str) -> None:
    """The one OPERATION with a handler (see `OPERATIONS`): the story
    swaps under the screen, so the break rule draws over the notice."""
    chat.ledger.rule()
    chat.say(api_stories.new(chat.session, raw))


def _lore(chat: Chat, raw: str) -> None:
    _browse_lore(chat, "scenes")


def _cast(chat: Chat, raw: str) -> None:
    _browse_lore(chat, "cast")


def _browse_lore(chat: Chat, lens: screen_lore.Lens) -> None:
    if chat.session.story_id is None:
        chat.say("No story yet — send a message first.")
        return
    if not api_lore.exists(chat.session):
        chat.say("No lore in this story yet — it builds as scenes close (see /extract).")
        return
    screen_lore.browse(chat.session, lens)


def _extract(chat: Chat, raw: str) -> None:
    """Schedule the forced pass, echo the worker's status on one updating
    line, Ctrl+C cancels; the report prints when the WorkerRun returns."""
    run = api_lore.extract(chat.session)
    report = _wait_run(chat, run, opening="Closing a scene…")
    if report is not None:
        chat.say(error_line(report) if run.failed else report)


def _wait_run(chat: Chat, run: WorkerRun, *, opening: str) -> str | None:
    """Wait on a forced pass in the foreground, the worker's progress on
    one updating (transient, self-erasing) line; the report when the pass
    returned, None when Ctrl+C cancelled it (the cancel notice said)."""
    shown = ""

    def transient(line: str) -> None:
        sys.stdout.write(f"\r{ERASE_LINE}{DIM}{line}{RESET}")
        sys.stdout.flush()

    sys.stdout.write(chat.ledger.said())
    transient(opening)
    try:
        while not run.settled(0.1):
            line = chat.session.status()
            if line and line != shown:
                shown = line
                transient(line)
    except KeyboardInterrupt:
        transient(run.cancel())
        sys.stdout.write("\n")
        sys.stdout.flush()
        return None
    sys.stdout.write(f"\r{ERASE_LINE}")
    sys.stdout.flush()
    return run.poll()


def _context(chat: Chat, raw: str) -> None:
    """Page the preview (long stories run to thousands of lines), the
    role markers dimmed on the way through. `otaku logs` shows what was
    actually sent; this shows what is about to be."""
    preview = api_reports.context(chat.session, dim=DIM, reset=RESET)
    # The pager holds the real stream; its output is past the ledger.
    chat.ledger.invalidate()
    # color=True keeps the dim markers through less (-R).
    click.echo_via_pager(preview, color=True)


def _card(chat: Chat, raw: str) -> None:
    """The terminal's path affordance, then the three-step import:
    resolve `FILE [NAME]` on THIS side (the longest leading token run
    naming a real file is the file, a leading `@` stripped, the rest
    renames), read the bytes, then prepare → ask the persona (tty only;
    the remembered default) → add. The exchange echoes like a played
    submission: the typed line (and the ask) erased and re-echoed as the
    grey block, the report and the greeting riding it — so /undo takes
    the screen back whole."""
    argument = raw.strip().removeprefix("@")
    if not argument:
        chat.say("Usage: /card FILE [NAME]")
        chat.ledger.invalidate()
        return
    path, rename = _file_and_name(argument)
    try:
        data = path.read_bytes()
    except OSError as e:
        chat.say(error_line(f"Could not read {path}: {e}"))
        chat.ledger.invalidate()
        return
    try:
        # The row records the argument as typed — a path is what the
        # terminal's user named the file, and /last must read it back.
        prepared = api_cards.prepare(
            chat.session, data, path.name, rename, line=f"/card {argument}"
        )
    except Refused as e:
        chat.say(str(e))
        chat.ledger.invalidate()
        return
    persona = _ask_persona(chat, api_cards.remembered_persona(chat.session) or "you")
    landed = api_cards.add(chat.session, prepared, persona)
    # The import plays like a submission.
    chat.ledger.echo_block(message(landed.line.body, "user"))
    out = chat.ledger.reply
    print(f"{DIM}[ {landed.report} ]{RESET}", file=out)
    if landed.greeting is not None:
        print(file=out)
        print(message(landed.greeting.body, "assistant"), file=out)


def _import(chat: Chat, raw: str) -> None:
    """Resolve and read the file on THIS side (`@` stripped), then
    api.transfer.import_file(text, name); wait on the extraction
    WorkerRun showing `session.status()`, then echo the landing under
    the break rule — as deep in the scene as any other way in."""
    text = raw.strip().removeprefix("@")
    if not text:
        chat.say("Usage: /import FILE")
        return
    path = Path(text).expanduser()
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        chat.say(error_line(f"Could not read {path}: {e}"))
        return
    result = api_transfer.import_file(chat.session, content, path.name)
    for notice in result.notices:
        chat.say(notice)
    if result.extraction is not None:
        sys.stdout.write("\n")  # the import's counts, then its extraction, apart
        report = _wait_run(chat, result.extraction, opening="Closing a scene…")
        if report is not None:
            chat.say(report)
    chat.ledger.rule()
    chat.say(last_turns(list(chat.session.messages), RESUME_TURNS))
    chat.restore_tail(RESUME_TURNS)


def _export(chat: Chat, raw: str) -> None:
    """Render the document, confirm an overwrite, write the file. No
    name writes `<story-title>.md` (or story.md) in the current
    directory; a name carrying no extension of its own gets `.md`, since
    the document is one; an existing file prompts before overwriting
    (default no). A leading `@` — the path-completion trigger — is not
    part of the name."""
    document = api_transfer.export(chat.session)
    name = raw.strip().removeprefix("@")
    path = Path(name).expanduser() if name else Path(api_transfer.export_name(chat.session))
    # An existing DIRECTORY keeps its name: `.md` would write a file
    # beside it, where the write refusing out loud is the honest answer.
    if not path.suffix and not path.is_dir():
        path = path.with_suffix(api_transfer.EXPORT_SUFFIX)
    # A name the filesystem will not even look up (too long, say) is not
    # an existing file: fall through, and let the write refuse out loud.
    if _existing_file(str(path)) is not None:
        sys.stdout.write(chat.ledger.said())
        try:
            answer = latin_key(input(f"{path} already exists — overwrite? [y/N] ").strip())
        except (EOFError, KeyboardInterrupt):
            chat.say("Cancelled.")
            return
        if answer not in YES_ANSWERS:
            chat.say("Not exported.")
            return
    try:
        path.write_text(document, encoding="utf-8")
    except OSError as e:
        chat.say(error_line(f"Could not write {path}: {e}"))
        return
    chat.say(f"Exported to {path}.")


def _model(chat: Chat, raw: str) -> None:
    """Bare: the picker screen (which executes a confirmed switch and
    returns the notice); with an argument: api.providers.switch_spec
    (the split rule lives there)."""
    if raw.strip():
        chat.say(_bold_switch(api_providers.switch_spec(chat.session, raw)))
        return
    notice = screen_models.pick(chat.session, initial_spec=chat.session.full_model_name)
    if notice:
        chat.say(_bold_switch(notice))


def _help(chat: Chat, raw: str) -> None:
    # Colored at print time, never at build: the table's column math runs
    # on plain text (escapes would count into the padding), and the theme
    # is only settled once the launch has asked the terminal.
    chat.say(highlight_commands(help_text(), command_tokens()))


def _bye(chat: Chat, raw: str) -> None:
    chat.quit = True


# token → handler, for every INTERACTIVE row of the shared table (and
# the one decorated OPERATION, /new — see OPERATIONS).
_INTERACTIVE: dict[str, Callable[[Chat, str], None]] = {
    "/undo": _undo,
    "/regen": _regen,
    "/last": _last,
    "/clear": _clear,
    "/stories": _stories,
    "/system": _system,
    "/new": _new,
    "/lore": _lore,
    "/cast": _cast,
    "/extract": _extract,
    "/context": _context,
    "/card": _card,
    "/import": _import,
    "/export": _export,
    "/model": _model,
    "/help": _help,
    "/bye": _bye,
}


# ---------- dispatch internals ----------


def _argument(line: str, token: str) -> str:
    """Everything after the spec's token, verbatim from the first
    non-space character — free-text arguments keep the user's exact
    spacing (split-and-rejoin would collapse it)."""
    rest = line
    for _ in token.split():
        _, _, rest = rest.lstrip().partition(" ")
    return rest.lstrip()


def _unknown(line: str) -> str:
    """The unknown-command sentence; the /set family's is composed FROM
    the shared table, so the usage line and the commands can never
    disagree."""
    word = line.split()[0]
    if word == "/set":
        forms = " | ".join(
            f"{spec.token} {spec.args}".strip()
            for spec in commands.COMMANDS
            if spec.token.startswith("/set ")
        )
        return f"Usage: {forms}"
    return f"Unknown command: {word}. Type /help."


def _file_and_name(raw: str) -> tuple[Path, str]:
    """`FILE [NAME]` split by what EXISTS: the longest leading run of
    tokens naming a real file is the file, the rest is the rename — so
    both a path with spaces and a multi-word name read correctly. Nothing
    matching falls through whole, for `read_bytes` to refuse honestly."""
    tokens = raw.split()
    for i in range(len(tokens), 0, -1):
        candidate = _existing_file(" ".join(tokens[:i]))
        if candidate is not None:
            return candidate, " ".join(tokens[i:]).strip()
    return Path(raw).expanduser(), ""


def _ask_persona(chat: Chat, default: str) -> str:
    """Who the player is in this story — `{{user}}` in every card text.
    Enter takes the default; a non-tty stdin never blocks on the ask.
    The echoed ask joins the typed rows (the lead blank included), so
    the block echo replaces it along with the typed line."""
    if not sys.stdin.isatty():
        return default
    lead = chat.ledger.said()
    if lead:
        sys.stdout.write(lead)
        chat.ledger.typed(lead)
    ask = f"User name for the card [{default}]: "
    answer = input(ask).strip()
    chat.ledger.typed(ask + answer + "\n")
    return answer or default


def _bold_switch(notice: str) -> str:
    """The switch confirmation with its model spec in bold — styling is
    the terminal's, so it is laid over the backend's sentence here, at
    the two doors that show one."""
    head = "Switched to "
    if notice.startswith(head) and notice.endswith("."):
        return f"{head}{BOLD}{notice[len(head) : -1]}{RESET}."
    return notice


def _existing_file(text: str) -> Path | None:
    """The file `text` names, or None when it names none — including
    when the filesystem REFUSES to answer: a command argument is text
    until proven a path, and the proof is a question the OS can decline
    (a component over 255 bytes raises ENAMETOOLONG instead of returning
    false). Anything the lookup itself raises means the same thing
    here — not a file. Beside its only consumers: the `_system`,
    `_card`, and `_export` file affordances above."""
    try:
        candidate = Path(text).expanduser()
        return candidate if candidate.is_file() else None
    except (OSError, ValueError, RuntimeError):
        return None
