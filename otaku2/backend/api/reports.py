"""The read-only reports both frontends show verbatim.

Everything here is plain text or plain data — the terminal pages or
prints it, the web shows it; neither rewrites it.
"""

from dataclasses import dataclass

from otaku2 import __version__
from otaku2.backend.api import stories
from otaku2.backend.session import NO_MODEL_HINT, Refused, Session
from otaku2.context.assembler import AssembledPrompt
from otaku2.formatting import format_context, format_size, pretty_path, printable, truncate_label
from otaku2.providers import CloudClient, ProviderConfig


def context(session: Session, *, dim: str = "", reset: str = "") -> str:
    """The next request EXACTLY as it will be sent, with token estimates
    per part above — `dim`/`reset` bracket the role markers so a terminal
    can fade them and the web can pass markers of its own. Nothing here
    is otaku's own text except those markers (standing for the JSON role
    field) and the summary — every other line is content the model
    receives, in order. No model: the preview still stands, over the
    assembler's default window — what WOULD be sent is a question that
    needs no server."""
    client = session._client()
    window = client.get_context_size(session.model) if client is not None else None
    prompt = session._assemble(window)
    return _render_preview(prompt, dim=dim, reset=reset)


def usage(session: Session, raw: str = "") -> str:
    """Tokens spent on this story — or on every story when `raw` is
    "all" (the one argument this command knows; anything else is Refused
    with the usage line). Grouped by what the tokens were spent on
    (chat, lore, …), then by provider and model — a column each. Raises
    Refused when there is nothing to report."""
    argument = raw.strip().lower()
    if argument not in ("", "all"):
        raise Refused("Usage: /usage [all]")
    everything = argument == "all"
    if not everything and session.story_id is None:
        raise Refused("No story yet — send a message first, or use /usage all.")
    rows = session._store.usage.get_totals(None if everything else session.story_id)
    if not rows:
        raise Refused(
            "No recorded usage yet." if everything else "No recorded usage for this story."
        )
    scope = "all stories" if everything else "this story"
    purpose_w = max(len("total"), max(len(r.purpose) for r in rows))
    provider_w = max(len(r.provider) for r in rows)
    model_w = max(len(r.model) for r in rows)
    # The text columns join with " · "; the header and total rows blank
    # the separator out, so the numeric columns stay aligned.
    head = f"  {'':<{purpose_w}}   {'':<{provider_w}}   {'':<{model_w}}"
    out = [
        f"Token usage — {scope}:",
        f"{head}  {'REQS':>5}  {'PROMPT':>10}  {'REPLY':>10}  {'TOK/S':>7}",
    ]
    for r in rows:
        rate = r.completion_tokens / r.seconds if r.seconds > 0 else 0.0
        out.append(
            f"  {r.purpose:<{purpose_w}} · {r.provider:<{provider_w}} · {r.model:<{model_w}}  "
            f"{r.requests:>5,}  {r.prompt_tokens:>10,}  {r.completion_tokens:>10,}  {rate:>7.1f}"
        )
    total_p = sum(r.prompt_tokens for r in rows)
    total_c = sum(r.completion_tokens for r in rows)
    total_r = sum(r.requests for r in rows)
    out.append(
        f"  {'total':<{purpose_w}}   {'':<{provider_w}}   {'':<{model_w}}"
        f"  {total_r:>5,}  {total_p:>10,}  {total_c:>10,}"
        f"  {'':>7}\n  ({total_p + total_c:,} tokens across {len(rows)} model/purpose pairs)"
    )
    return "\n".join(out)


def info(session: Session) -> str:
    """Everything otaku knows about the active model and session,
    best-effort: network-backed fields are silently skipped. Without a
    model only that half is missing: the state dir, the story, its
    premise and the parameters are the session's own, and reporting them
    needs no provider."""
    out = [f"State dir: {pretty_path(session._paths.root)}", ""]
    if session._client() is None:
        out.append(NO_MODEL_HINT)
    else:
        out.extend(_model_lines(session))
    out.append("")
    out.extend(_session_lines(session))
    return "\n".join(out)


def balances(session: Session) -> str:
    """The aligned provider/balance report, for the engines that have an
    account to bill — the cloud catalogs, queried concurrently, the
    unreachable simply skipped. Raises Refused when none answers."""

    def probe(provider: str, config: ProviderConfig) -> tuple[str, str] | None:
        client = session._providers_registry.get_client(provider)
        if not isinstance(client, CloudClient):
            return None  # a local engine has no account to ask
        try:
            value = client.balance(timeout=5.0)
        except Exception:
            return None
        return (provider, value) if value else None

    rows = [row for row in session._providers_registry.map(probe) if row]
    if not rows:
        raise Refused("Cannot get balances from cloud providers.")
    width = max(len(name) for name, _ in rows)
    return "\n".join(f"{name:<{width}}  {value}" for name, value in rows)


@dataclass(frozen=True)
class BannerFacts:
    """What the session header states; the frontend owns the drawing."""

    version: str
    model: str  # "(no model)" when none
    engine: str  # the client's kind; "" when none
    context: int | None  # the loaded window, when a LOCAL engine answers
    story: str  # the headline; "" when none


def banner(session: Session) -> BannerFacts:
    """Best-effort and never blocking on the internet: a cloud catalog is
    not asked for its context window at launch — its answer lives across
    the internet, and a launch does not wait for that."""
    window = None
    engine = ""
    client = session._client()
    if client is not None:
        engine = client.kind
        if client.local:
            try:
                window = client.get_context_size(session.model)
            except Exception:
                window = None
    return BannerFacts(
        version=__version__,
        model=session.model or "(no model)",
        engine=engine,
        context=window,
        story=stories.headline(session),
    )


def on_cloud(session: Session) -> bool:
    """Whether the story is played against a hosted catalog — the prompt
    marker's question, answered per turn."""
    client = session._client()
    return client is not None and not client.local


# ---------- report internals ----------


def _model_lines(session: Session) -> list[str]:
    """The active model's half of `info` — the caller checked a model is
    active."""
    client = session._client()
    assert client is not None
    # The registry's copy, not a snapshot: a URL or key edited in the
    # picker panel shows here immediately.
    config = client.config
    out = [f"Model:    {session.full_model_name}", f"Engine:   {client.kind} ({config.url})"]
    if config.api_key:
        out.append("Auth:     api_key configured")
    # The model's own row — load state only where loading is a real state
    # (a plain endpoint or a cloud catalog serves everything statically).
    # A cloud catalog has neither a load state nor a size to report, and
    # asking costs a full catalog fetch: skip what would print nothing.
    row = client.model(session.model) if client.local else None
    if row is not None and client.local and client.kind != "openai":
        out.append(f"Loaded:   {'yes' if row.loaded else 'no'}")
    if row is not None and row.size:
        out.append(f"Size:     {format_size(row.size)}")
    window = format_context(client.get_context_size(session.model))
    if window:
        out.append(f"Context:  {window}")
    if client.supports_thinking:
        out.append(f"Thinking: {session.think if session.think else 'default'}")
    else:
        out.append("Thinking: not supported")
    if config.keep_alive:
        out.append(f"Keep-alive: {config.keep_alive}")
    return out


def _session_lines(session: Session) -> list[str]:
    """The session's half of `info` — what is loaded, not what answers."""
    out = []
    if label := stories.headline(session):
        out.append(f"Story:    {truncate_label(label, stories.LABEL_WIDTH)}")
    out.append(f"Messages: {len(session.messages)}")
    if session.system:
        out.append(f'System:   "{session.system}"')
    if session.params:
        rendered = ", ".join(f"{k} = {v}" for k, v in session.params.items())
        out.append(f"Parameters: {rendered}")
    return out


def _render_preview(prompt: AssembledPrompt, *, dim: str, reset: str) -> str:
    """The context view's text (see `context`)."""
    lines = ["Context preview — the exact request to be sent. Context summary:", ""]
    used = round(100 * prompt.total_tokens / prompt.context_max) if prompt.context_max else 0
    lines.append(
        f"  ~{prompt.total_tokens:,} tokens · {used}% of the {prompt.context_max:,} window"
    )
    if prompt.system_tokens:
        lines.append(f"  system {prompt.system_tokens:,} · transcript {prompt.transcript_tokens:,}")
    # The summaries are not a third slice of the transcript: they STAND IN
    # for the messages between head and tail. Naming that count is what
    # makes the line add up to the story's length instead of to nothing.
    tail = prompt.transcript_kept - prompt.head_count
    middle = prompt.transcript_total - prompt.transcript_kept
    if prompt.scenes_rolled_up:
        # Displaced summaries are named, not folded in: the rollup covers
        # the dropped scenes, and the line says so or the count would
        # claim the kept summaries cover the whole middle.
        plural = "s" if prompt.scenes_rolled_up != 1 else ""
        lines.append(
            f"  {prompt.head_count} head + {tail} tail verbatim, plus {middle} middle "
            f"inserted in between as a rollup and {prompt.scenes_summarized} last scene "
            f"summaries. the rollup includes {prompt.scenes_rolled_up} older scene{plural}"
        )
    elif prompt.scenes_summarized:
        lines.append(
            f"  {prompt.head_count} head + {tail} tail verbatim, plus {middle} middle "
            f"inserted in between as {prompt.scenes_summarized} scene summaries"
        )
    else:
        lines.append(f"  {prompt.transcript_kept} messages verbatim")

    for turn in prompt.messages:
        lines.append("")
        lines.append(f"{dim}[{turn.role}]{reset}")
        lines.extend(_preview_body(printable(turn.body), prompt.recap))
    return "\n".join(lines)


def _preview_body(text: str, recap: str) -> list[str]:
    """Content lines for the preview. Blank lines are dropped to keep it
    tight, EXCEPT in the turn carrying the recap, where paragraph breaks
    are load-bearing: they separate one scene summary from the next (and
    the last summary from any message text merged in after it)."""
    if recap and recap in text:
        out: list[str] = []
        for line in text.splitlines():
            if line.strip():
                out.append(line)
            elif out and out[-1] != "":
                out.append("")  # collapse runs, keep one
        return out
    return [line for line in text.splitlines() if line.strip()]
