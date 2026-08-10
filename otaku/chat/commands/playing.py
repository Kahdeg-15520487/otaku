"""The playing commands: /undo, /regen, /last, /clear.

The roleplay directions /me, /you and /ooc are NOT commands — they are
prompt syntax, read off the typed line by `formatting.parse_prompt` and
played by `repl._play` like any other prompt.

/undo and /regen work the
screen through the ledger (chat/screen.py): the erased exchange or reply
simply vanishes, and only when the ledger cannot prove the erase do they
fall back to reporting — every fallback print invalidates the ledger,
because it lands below the exchange it describes, and draws the ledger's
break rule over what it says.
"""

from otaku.chat import rendering
from otaku.chat.framing import framing
from otaku.chat.inference import run_inference
from otaku.chat.session import NO_MODEL_HINT, Session
from otaku.store import Store
from otaku.terminal import DIM, RESET

# Turns /last shows when called bare — a turn being an exchange, the
# prompt and its reply (two message rows).
_LAST_TURNS_DEFAULT = 5


def cmd_undo(session: Session, store: Store, args: list[str]) -> None:
    """Discard the last exchange: the reply plus the prompt that caused it.
    Nothing is deleted — the head moves back and the undone turns stay in
    the tree as siblings. When the exchange still sits directly above the
    prompt, it is erased from the screen as if never played; otherwise the
    new ending is reported. The re-echoed turns below the report are
    turns — the next /undo or /regen works them — and taking them takes
    the report too, a fresh one printing in its place: the screen always
    shows one, current, report."""
    popped = session.undo(store)
    if not popped:
        session.screen.invalidate()
        print("Nothing to undo.")
        return
    refreshing = session.screen.top_is_report()
    if session.screen.erase_exchange():
        if refreshing:
            session.screen.take_suppressed_gap()  # output follows after all
            _report_undo_ending(session)
        return  # otherwise the ending is still on screen — say nothing
    session.screen.invalidate()
    _report_undo_ending(session)


def _report_undo_ending(session: Session) -> None:
    """The story's new ending, reported and re-echoed — and handed back to
    the ledger, the report line included, so the next /undo or /regen
    works the re-echoed turns."""
    session.screen.rule()
    if not session.messages:
        print("Undone. The story is now empty (its turns stay in the tree).")
        return
    report = f"{DIM}[ undone. the story now ends with: ]{RESET}"
    print(report)
    print()
    print(session.render_last_turns(2))
    session.restore_screen_tail(2, above=report)


def cmd_regen(session: Session, store: Store, args: list[str]) -> None:
    """Re-run the last prompt: the current reply becomes a sibling in the
    tree and a fresh one streams — in the old one's place when the screen
    allows. A prompt left unanswered is simply sent again: nothing to
    sibling, and the take streams straight under the standing prompt —
    over the error line a failed request left, or into the empty space
    below a prompt that was never answered at all. When the screen is
    beyond reach, the marker announces and the prompt being re-run echoes
    under it, like an undo report shows its turns: the new take reads as
    an exchange, and /undo and /regen keep working it."""
    if session.provider_config is None:
        # Before anything is dropped or erased: without a model there is
        # no fresh take, and the standing reply must survive untouched.
        print(NO_MODEL_HINT)
        return
    popped = session.drop_last_reply(store)
    # The prompt the take re-runs — absent when the story is a promptless
    # reply, which regenerates on its own.
    prompt = session.messages[-1] if session.messages else None
    if popped is None and prompt is None:
        session.screen.invalidate()
        print("Nothing to regenerate.")
        return
    if not session.screen.erase_reply():
        session.screen.invalidate()
        session.screen.rule()
        marker = f"{DIM}[ regenerating ]{RESET}"
        print(marker)
        print()
        # The typed line stays above the marker — nothing of it to erase.
        session.screen.typed_rows = 0
        echo = rendering.message(prompt.body, "user", config=session.config) if prompt else ""
        session.screen.echo_block(echo, above=marker)
    # The prompt decides what its answer is, exactly as when it first
    # played — and it decides even for a replaced reply, so an edit in the
    # picker is honoured. Only a promptless reply has nothing to ask, and
    # then the reply it replaces says what it was.
    if prompt is not None:
        kind = framing(prompt.body).reply_kind
    else:
        kind = popped.kind if popped is not None else "dialogue"
    run_inference(session, store, reply_kind=kind)


def cmd_last(session: Session, store: Store, args: list[str]) -> None:
    """`/last [N]` — show the last N turns again (default 5), the way a
    relaunch shows the scene: a clean view after undos, regens, etc. The
    break rule separates the copy from the turns it repeats and a report
    names what it shows, like an undo report names the ending; the echoed
    turns go back to the ledger, so /undo and /regen work them like
    freshly played ones."""
    if args and not (args[0].isdigit() and int(args[0]) > 0):
        print("Usage: /last [N]")
        return
    count = int(args[0]) if args else _LAST_TURNS_DEFAULT
    if not session.messages:
        print("No turns yet.")
        return
    rows = count * 2  # a turn is two message rows
    session.screen.rule()
    # What the echo actually holds, never what was asked for: a short
    # story shows everything it has, and the report must not over-claim.
    shown = (len(session.messages[-rows:]) + 1) // 2
    report = f"The last {shown} turns of this story:"
    print(report)
    print()
    print(session.render_last_turns(rows))
    session.restore_screen_tail(rows, above=report)


def cmd_clear(session: Session, store: Store, args: list[str]) -> None:
    """`/clear` — wipe the screen; the story is untouched and `/last`
    brings the scene back. The next prompt opens at the top."""
    session.screen.clear()
