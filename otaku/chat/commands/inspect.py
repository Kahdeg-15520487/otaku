"""Inspection commands: /context, /usage, /balance, and /info."""

import click

from otaku.chat.session import NO_MODEL_HINT, Session
from otaku.formatting import format_context, format_size, pretty_path, printable
from otaku.lore import assembler
from otaku.providers.base import CloudClient
from otaku.settings.config import ProviderConfig
from otaku.store import Store
from otaku.terminal import DIM, RESET, error_line


def cmd_context(session: Session, store: Store, args: list[str]) -> None:
    """Preview the next request: token estimates per part, the system text
    (yours alone), and the transcript exactly as it will be sent. `otaku
    logs` shows what was actually sent; this shows what is about to be."""
    context = None
    if session.provider_config is not None:
        client = session.providers.get_client(session.provider_config.name)
        context = client.get_context_size(session.model)
    # No model: the preview still stands, over the assembler's default
    # window — what WOULD be sent is a question that needs no server.
    prompt = assembler.assemble_story(store, session, context)
    preview = _render_preview(prompt, dim=DIM, reset=RESET)
    # Long stories make this thousands of lines; page it like `otaku logs`.
    # color=True keeps the dim markers through less (-R).
    click.echo_via_pager(preview, color=True)


def cmd_usage(session: Session, store: Store, args: list[str]) -> None:
    """`/usage` — tokens spent in this story. `/usage all` — every story in
    the database. Grouped by what the tokens were spent on (chat, lore, …),
    then by provider and model — a column each."""
    everything = bool(args) and args[0].lower() == "all"
    if not everything and session.story_id is None:
        print("No story yet — send a message first, or use /usage all.")
        return
    rows = store.usage.get_totals(None if everything else session.story_id)
    if not rows:
        print("No recorded usage yet." if everything else "No recorded usage for this story.")
        return

    scope = "all stories" if everything else "this story"
    purpose_w = max(len("total"), max(len(r.purpose) for r in rows))
    provider_w = max(len(r.provider) for r in rows)
    model_w = max(len(r.model) for r in rows)
    # The text columns join with " · "; the header and total rows blank
    # the separator out, so the numeric columns stay aligned.
    head = f"  {'':<{purpose_w}}   {'':<{provider_w}}   {'':<{model_w}}"
    print(f"Token usage — {scope}:")
    print(f"{head}  {'REQS':>5}  {'PROMPT':>10}  {'REPLY':>10}  {'TOK/S':>7}")
    for r in rows:
        rate = r.completion_tokens / r.seconds if r.seconds > 0 else 0.0
        print(
            f"  {r.purpose:<{purpose_w}} · {r.provider:<{provider_w}} · {r.model:<{model_w}}  "
            f"{r.requests:>5,}  {r.prompt_tokens:>10,}  {r.completion_tokens:>10,}  {rate:>7.1f}"
        )
    total_p = sum(r.prompt_tokens for r in rows)
    total_c = sum(r.completion_tokens for r in rows)
    total_r = sum(r.requests for r in rows)
    print(
        f"  {'total':<{purpose_w}}   {'':<{provider_w}}   {'':<{model_w}}"
        f"  {total_r:>5,}  {total_p:>10,}  {total_c:>10,}"
        f"  {'':>7}\n  ({total_p + total_c:,} tokens across {len(rows)} model/purpose pairs)"
    )


def cmd_balance(session: Session, store: Store, args: list[str]) -> None:
    """Account balance per configured provider, for the backends that
    report one — the cloud catalogs; a local engine has nothing to bill.
    Queried concurrently, an unreachable provider simply skipped."""

    def probe(name: str, provider_config: ProviderConfig) -> tuple[str, str] | None:
        client = session.providers.get_client(name)
        if not isinstance(client, CloudClient):
            return None  # a local engine has no account to ask
        try:
            value = client.balance(timeout=5.0)
        except Exception:
            return None
        return (name, value) if value else None

    rows = [row for row in session.providers.map(probe) if row]
    if not rows:
        print(error_line("Cannot get balances from cloud providers."))
        return
    width = max(len(name) for name, _ in rows)
    for name, value in rows:
        print(f"{name:<{width}}  {value}")


def cmd_info(session: Session, store: Store, args: list[str]) -> None:
    """Best-effort dump of everything otaku knows about the active model and
    session. Network-backed fields are silently skipped when the provider
    doesn't expose them or the request fails. Without a model only that
    half is missing: the state dir, the story, its premise and the
    parameters are the session's own, and reporting them needs no
    provider."""
    print(f"State dir: {pretty_path(session.paths.root)}")
    print()
    if session.provider_config is None:
        print(NO_MODEL_HINT)
    else:
        _print_model(session, session.provider_config.name)
    print()
    _print_session(session, store)


def _print_model(session: Session, provider_name: str) -> None:
    """The active model's half of `/info` — the provider name passed in by
    the caller that checked a model is active."""
    client = session.providers.get_client(provider_name)
    # The registry's copy, not the session's snapshot: a URL or key edited
    # in the picker panel shows here immediately.
    provider_config = client.provider_config
    print(f"Model:    {session.full_model_name}")
    print(f"Backend:  {client.kind} ({provider_config.url})")
    if provider_config.api_key:
        print("Auth:     api_key configured")

    # The model's own row — load state only where loading is a real state
    # (a plain endpoint or a cloud catalog serves everything statically).
    # A cloud catalog has neither a load state nor a size to report, and
    # asking costs a full catalog fetch: skip what would print nothing.
    row = client.model(session.model) if client.local else None
    if row is not None and client.local and client.kind != "openai":
        print(f"Loaded:   {'yes' if row.loaded else 'no'}")

    if row is not None and row.size:
        print(f"Size:     {format_size(row.size)}")

    context = format_context(client.get_context_size(session.model))
    if context:
        print(f"Context:  {context}")

    if client.supports_thinking:
        print(f"Thinking: {session.think if session.think else 'default'}")
    else:
        print("Thinking: not supported")

    if provider_config.keep_alive:
        print(f"Keep-alive: {provider_config.keep_alive}")


def _print_session(session: Session, store: Store) -> None:
    """The session's half of `/info` — what is loaded, not what answers."""
    if label := session.story_headline(store):
        print(f"Story:    {label}")
    print(f"Messages: {len(session.messages)}")
    if session.system:
        print(f'System:   "{session.system}"')
    if session.params:
        rendered = ", ".join(f"{k} = {v}" for k, v in session.params.items())
        print(f"Parameters: {rendered}")


def _render_preview(prompt: assembler.AssembledPrompt, *, dim: str = "", reset: str = "") -> str:
    """The `/context` view: the request EXACTLY as it will be sent. Nothing
    here is otaku's own text except the dim `[role]` markers (standing for
    the JSON role field) and the token summary above — every other line is
    content the model receives, in order."""
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
    if prompt.scenes_summarized:
        lines.append(
            f"  {prompt.head_count} head + {tail} tail verbatim, plus {middle} middle "
            f"inserted in between as {prompt.scenes_summarized} scene summaries"
        )
    else:
        lines.append(f"  {prompt.transcript_kept} messages verbatim")

    for message in prompt.messages:
        lines.append("")
        lines.append(f"{dim}[{message.role}]{reset}")
        lines.extend(_preview_body(printable(message.body), prompt.recap))
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
