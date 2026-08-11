"""The command surface: every command, what it takes, what it is called.

One table, `_HELP_ROWS`, and everything read off it — the /help text, the
menu's descriptions, whether a row is finished as it stands, and the
vocabulary display picks commands out by. Its labels ARE the declaration:
a command not written here is not offered, not described, and not
highlighted.

A LEAF of `chat`: it imports nothing from its own package (nothing at
all, in fact), so any module may read it. That is the whole point —
`chat.commands` owns the handlers and therefore imports `chat.session`,
which puts the dispatch table downstream of half the package. The names
are upstream of everything, so they live apart from the handlers that
answer to them.
"""

import re

# A command as a label writes it: a slash and a word, nothing else. Rules
# out the `/` in "Up / Down" and the `@` and `"""` rows, which are keys at
# the prompt rather than commands.
_COMMAND_LABEL = re.compile(r"^/[a-z]+$")

# (command, shortcut, description) per row; "" for no shortcut, None starts
# a group heading. One row per source line, whatever its width — E501 is
# off for this file (see pyproject) and the formatter is off for the table.
# fmt: off
_HELP_ROWS: list[tuple[str | None, str, str]] = [
    (None, "", "Playing:"),
    ("PROMPT", "", "Your character speaks or acts; the model continues the scene — sent verbatim"),
    ("/me NAME: PROMPT", "", "Send PROMPT, hinting the model that you write as NAME"),
    ("/you NAME[: HINT]", "", "Tell the model to play NAME; optional HINT rides the turn"),
    ("/ooc PROMPT", "", "Talk to the model out of character"),
    ("/undo", "Ctrl+U", "Discard the last turn"),
    ("/regen", "Ctrl+R", "Re-run the last prompt (mid-stream: cancel + regen)"),
    ("/last [N]", "", "Show the last N turns (default 5) — a clean view after undos, regens, etc."),
    ("/clear", "", "Clear the screen"),
    (None, "", "Inside a prompt:"),
    ("… /ooc TEXT", "", "An aside out of character"),
    ("… /cue TEXT", "", "Steer just the next reply — not kept in context afterwards"),
    (None, "", "Stories:"),
    ("/stories", "Ctrl+T", "Browse stories, resume an old one"),
    ("/fork [TITLE]", "", "Continue in a copy of this story; the original stays"),
    ("/system <text | FILE>", "", "Set the system prompt for this story — either directly or from a file"),
    ("/title NEW", "", "Set the story title"),
    ("/new", "", "Clear context and start a new story"),
    (None, "", "Lore:"),
    ("/lore", "Ctrl+L", "Browse and edit the memory: scenes, cast, journals"),
    ("/cast", "", "The same browser, opened directly on the cast"),
    ("/extract", "", "Extract lore from the recent messages now; triggered automatically after 5 minutes of inactivity"),
    ("/merge A into B", "", "Fold a duplicate character into the real one"),
    (None, "", "Inspect:"),
    ("/context", "", "Preview the next request (assembled prompt + budgets)"),
    ("/usage [all]", "", "Tokens spent on this story (or everything)"),
    ("/balance", "", "Account balance of cloud providers"),
    ("/info", "", "Show details about the current model + session"),
    (None, "", "Import/export:"),
    ("/card FILE [NAME]", "", "Import a character card (PNG or JSON) into this story — NAME renames them"),
    ("/import FILE", "", "Import a story: an otaku export, SillyTavern chat (.jsonl), or plain text"),
    ("/export [FILE]", "", "Export the whole story to Markdown (memory + messages)"),
    (None, "", "Model and settings:"),
    ("/model [PROVIDER/MODEL]", "Ctrl+O", "Switch model"),
    ("/set think <level>", "", "Thinking effort for the model: on|off|none|low|medium|high|max|default"),
    ("/set parameter <name> <val>", "", "Set an inference parameter for the model; no <val> shows it, <val> = reset returns the default"),
    ("/set verbose on|off", "", "Show the stats line after each reply"),
    ("/set autocorrect on|off", "", "Settle a character name you type in /you and /me commands to the cast's own spelling"),
    ("", "", ""),
    ("/help", "", "Show this help"),
    ("/bye", "Ctrl+D", "Exit"),
    (None, "", "Keys at the prompt:"),
    ('"""', "", 'Begin a multiline message; close it with """'),
    ("@", "", "In a FILE argument: enable path autocompletion"),
    ("Up / Down", "", "Walk your recent prompt history"),
    ("Ctrl+C", "", "Clear the current line; cancel an in-flight reply"),
]
# fmt: on


def _build_help() -> str:
    cmd_width = max(len(row[0]) for row in _HELP_ROWS if row[0])
    key_width = max(len(row[1]) for row in _HELP_ROWS)
    lines: list[str] = []
    for command, key, desc in _HELP_ROWS:
        if command is None:  # a group heading — one blank line before it
            if lines:
                lines.append("")
            lines.append(desc)
            continue
        lines.append(f"  {command:<{cmd_width}} {key:<{key_width}}  {desc}".rstrip())
    return "\n".join(lines)


HELP_TEXT = _build_help()


def command_tokens() -> tuple[str, ...]:
    """Every slash word the app answers to, in help order — the commands
    typed at a line's start and the inliners typed inside one, which a
    label writes behind a `…`. What display reads to tell a command from
    prose: `/me` is one, `and/or` is not, so a highlighter never has to
    guess from the slash alone."""
    found = (word for label, _, _ in _HELP_ROWS if label for word in label.split())
    return tuple(dict.fromkeys(word for word in found if _COMMAND_LABEL.match(word)))


def describe_command(tokens: tuple[str, ...]) -> str:
    """The help description for a command path — ("/set", "think") → its
    row — read from _HELP_ROWS so the menu and /help can never disagree."""
    row = _help_row(tokens)
    return row[2] if row else ""


def arguments(tokens: tuple[str, ...]) -> str:
    """What a command takes, spelled as its /help row spells it —
    ("/me",) -> "NAME: PROMPT", ("/usage",) -> "[all]". Empty when it takes
    nothing. The menu shows this beside the command, so the shape of the
    line is visible while it is being typed rather than only in /help."""
    row = _help_row(tokens)
    return " ".join(row[0].split()[len(tokens) :]) if row else ""


def needs_argument(tokens: tuple[str, ...]) -> bool:
    """Whether this command is INCOMPLETE as it stands — its /help row names
    something that must follow, a parameter (`/me NAME: PROMPT`) or a
    subcommand (`/set think`). The menu adds a space when it accepts one,
    so the rest can be typed straight on, and Enter fills rather than sends.

    A bracketed follower is optional (`/usage [all]`, `/last [N]`), and the
    bare command is both valid and the usual thing meant — so it takes no
    space and Enter sends it. Reaching the option is then a space away,
    which is the right cost for the rarer choice."""
    row = _help_row(tokens)
    if row is None:
        return False
    parts = row[0].split()
    return len(parts) > len(tokens) and not parts[len(tokens)].startswith("[")


def _help_row(tokens: tuple[str, ...]) -> tuple[str, str, str] | None:
    """The _HELP_ROWS row a command path names, matched on the label's
    leading tokens. Group headings carry no label and never match."""
    for label, key, description in _HELP_ROWS:
        if label is None:
            continue
        parts = label.split()
        if len(parts) >= len(tokens) and tuple(parts[: len(tokens)]) == tokens:
            return label, key, description
    return None
