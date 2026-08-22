"""The session's knobs: the /set family.

Values persist where they belong — state.toml for session-wide toggles,
models.toml per model — and never in the user-owned config. Every
operation takes the raw argument text and parses it itself; every one
returns the confirmation to show and raises Refused for what it
declines.
"""

from otaku.backend.session import KNOWN_PARAMS, NO_MODEL_HINT, Refused, Session
from otaku.settings import models as models_file
from otaku.settings.state import THINK_DEFAULT, THINK_LEVELS

_ON = ("on", "true", "yes")
_OFF = ("off", "false", "no")
# The typed sugar over the stored levels — a command-surface convenience,
# where THINK_LEVELS is what state.toml may hold.
THINK_ALIASES = {"on": "medium", "off": "none"}


def set_think(session: Session, raw: str) -> str:
    """A THINK_LEVELS value, an alias (on/off), or "default" (send
    nothing); "" reports where it stands. Raises Refused for an unknown
    level, no model, or an engine without the knob."""
    if not raw.strip():
        return f"Think: {session.think if session.think else 'default'}."
    value = THINK_ALIASES.get(raw.strip().lower(), raw.strip().lower())
    if value == THINK_DEFAULT:
        session._update_state(think=THINK_DEFAULT)
        return "Think: default (nothing sent — the model decides)."
    if value not in THINK_LEVELS:
        raise Refused("Usage: /set think on|off|none|low|medium|high|max|default")
    client = session._client()
    if client is None:
        raise Refused(NO_MODEL_HINT)
    if value != "none" and not client.supports_thinking:
        raise Refused(f"Thinking is not supported by provider {session.provider!r}.")
    session._update_state(think=value)
    return f"Think: {value}."


def set_verbose(session: Session, raw: str) -> str:
    """Session-wide and persisted — verbose is a UI preference, never a
    per-model setting. "" reports where it stands."""
    value = raw.strip().lower()
    if value:
        if value in _ON:
            session._update_state(verbose=True)
        elif value in _OFF:
            session._update_state(verbose=False)
        else:
            raise Refused("Usage: /set verbose on|off")
    return f"Verbose: {'on' if session.verbose else 'off'}."


def set_autocorrect(session: Session, raw: str) -> str:
    """Session-wide and persisted, like verbose. Off means a name reaches
    the story exactly as it was typed, whoever the cast says that is."""
    value = raw.strip().lower()
    if value:
        if value in _ON:
            session._update_state(autocorrect=True)
        elif value in _OFF:
            session._update_state(autocorrect=False)
        else:
            raise Refused("Usage: /set autocorrect on|off")
    return f"Autocorrect: {'on' if session.autocorrect else 'off'}."


def set_notification(session: Session, raw: str) -> str:
    """Session-wide and persisted, like verbose. On means a reply landing
    calls you back to the screen — with what, and whether the terminal
    can, is the frontend's business."""
    value = raw.strip().lower()
    if value:
        if value in _ON:
            session._update_state(notification=True)
        elif value in _OFF:
            session._update_state(notification=False)
        else:
            raise Refused("Usage: /set notification on|off")
    return f"Notification: {'on' if session.notification else 'off'}."


def set_parameter(session: Session, raw: str) -> str:
    """`<name> [value]` over KNOWN_PARAMS: set it ("reset" returns the
    model's own default; a bare name reports where it stands; "" lists
    what is set), auto-saved per model. Raises Refused for an unknown
    name or an unparsable value."""
    tokens = raw.split()
    if not tokens:
        if not session.params:
            return "No parameters set."
        rows = "\n".join(f"  {name} = {value}." for name, value in session.params.items())
        return f"Parameters:\n{rows}"
    if session._client() is None:
        raise Refused(NO_MODEL_HINT)
    name = tokens[0]
    if name not in KNOWN_PARAMS:
        raise Refused(f"Unknown parameter {name!r}. Known: {', '.join(KNOWN_PARAMS)}.")
    value_raw = " ".join(tokens[1:])
    if not value_raw:
        # Asking is not setting: the bare name shows where it stands.
        if name in session.params:
            return f"{name} = {session.params[name]}"
        return f"Parameter {name} is at the model's own default."
    # The literal `reset` returns the parameter to the model's own
    # default — here and in the saved file.
    if value_raw.lower() == "reset":
        if name not in session.params:
            return f"Parameter {name} is already at its default."
        session._params.pop(name)
        return f"Parameter {name} reset to default{_save_params(session)}"
    coerce = KNOWN_PARAMS[name]
    try:
        value = coerce(value_raw)
    except ValueError:
        raise Refused(f"Could not parse {value_raw!r} as {coerce.__name__}.") from None
    session._params[name] = value
    return f"{name} = {value}{_save_params(session)}"


def _save_params(session: Session) -> str:
    """Persist the model's parameters; the sentence tail says when the
    save did not land (the session still took the value)."""
    try:
        models_file.save_parameters(session._paths.models_file, session.model, dict(session.params))
    except (OSError, ValueError) as e:
        return f" (this session only — could not save: {e})."
    return "."
