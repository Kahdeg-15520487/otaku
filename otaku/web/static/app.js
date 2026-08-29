/* The page over an open session: what it asks for at boot, and every
   DOM listener it ever registers — both in one place, so "what is wired
   when this loads?" is answered by reading one function.

   The three rules the medium forces on us, kept where they are enforced:

   - A screen is opened by a BUTTON, and every one of them goes through
     `commands.run`. A button carries the token the contents rail keys
     by, never behaviour of its own — and never its label as a decision,
     which is why every one of them has a `data-` attribute instead.
   - Esc is ours, not the dialog's. A native <dialog> closes itself on
     Esc before anything else is asked, which would collapse every depth
     into one: clearing a filter and leaving a field editor would both
     shut the whole popup. So `cancel` is refused and Esc is routed here.
   - Bodies arrive verbatim. Nothing on this side rewrites the text. */

import * as api from "./js/api.js";
import { closeAll } from "./js/browser.js";
import { keepsScreen, openMessages, run as runCommand } from "./js/commands.js";
import { focusComposer, primeHistory, wire as wireComposer } from "./js/composer.js";
import { $, $$, watchTextareas } from "./js/dom.js";
import { disconnected, showFacts, watchServer } from "./js/shell.js";
import { load as loadTable } from "./js/table.js";
import { showTurns } from "./js/transcript.js";
import { watchForChanges } from "./js/watch.js";

async function boot() {
  try {
    const [facts, language, turns, history] = await Promise.all([
      api.facts(),
      api.syntax(),
      api.turns(),
      api.history(),
    ]);
    loadTable(language);
    showFacts(facts);
    showTurns(turns);
    primeHistory(history);
    disconnected(false);
  } catch {
    disconnected();
  }
}

function start() {
  wireComposer();
  watchTextareas();
  /* One stream, opened once and held: what is on disk is what the
     browser has, so a page whose files changed under it replaces
     itself. Not in `boot`, which runs again every time otaku comes
     back — that would leave a stream open per restart. */
  watchForChanges();
  /* The heartbeat and the connected mark, both directions — the page
     finds out that otaku stopped, and that it is back, in which case
     `boot` runs again: a restarted otaku may be open on another story. */
  watchServer(boot);

  // Every command button, wherever it is: the contents, a panel's
  // header, the turn bar beside the composer.
  document.addEventListener("click", (event) => {
    const command = event.target.closest("[data-command]");
    if (command) {
      /* A command carried by a panel's own chrome — the dossier's
         "Extract now", its "← All stories" — answers into the flow,
         which is behind the modal. Close first, so the reader sees what
         it did. Unless it ASKS first: a question belongs over the
         screen it was asked from, and a cancelled one must leave that
         screen exactly as it was (`commands.confirmed` closes them once
         it is answered). */
      if (command.closest("dialog[open]") && !keepsScreen(command.dataset.command)) closeAll();
      runCommand(command.dataset.command);
      foldRail();
      return;
    }
    // The contents row that is not a command: the open story's messages.
    if (event.target.closest("button[data-goto]")) {
      openMessages();
      foldRail();
      return;
    }
    if (event.target.closest("#otk-rail-toggle")) {
      toggleRail();
      return;
    }
    // The two verbs beside the composer, and the "try again" a failure
    // offers. A verb with nothing to act on is marked, not removed —
    // `aria-disabled` keeps it in the row and out of reach.
    const turn = event.target.closest("[data-turn]");
    if (turn && turn.getAttribute("aria-disabled") !== "true") {
      runCommand(turn.dataset.turn === "undo" ? "/undo" : "/regen");
    }
  });

  for (const dialog of $$("dialog")) {
    dialog.addEventListener("cancel", (event) => event.preventDefault());
    $(".otk-close", dialog)?.addEventListener("click", () => dialog.close());
    /* Leaving a screen puts the reader back where the story is written.
       Only when nothing else is up: closing a dialog that was opened
       over a panel returns to the panel, not past it to the page. */
    dialog.addEventListener("close", () => {
      if (!$("dialog[open]")) focusComposer();
    });
    // The scrim closes it, as a scrim does. A click on the dialog's own
    // padding reports the dialog as its target too, so the test is where
    // the pointer WAS: outside the panel's box, or not a pointer at all
    // (a keyboard-activated button reports the button, never this).
    dialog.addEventListener("click", (event) => {
      if (event.target !== dialog) return;
      const box = dialog.getBoundingClientRect();
      const outside =
        event.clientX < box.left ||
        event.clientX > box.right ||
        event.clientY < box.top ||
        event.clientY > box.bottom;
      if (outside) dialog.close();
    });
  }

  document.addEventListener("keydown", onKey);
}

/* The contents fold away on a narrow window and the spine carries the
   toggle; a row taken folds them back, so the panel it opened is not
   behind a drawer. */
function toggleRail(force) {
  const rail = $("#otk-rail");
  const toggle = $("#otk-rail-toggle");
  if (!rail || !toggle) return;
  const open = force !== undefined ? force : rail.dataset.open !== "true";
  rail.dataset.open = String(open);
  toggle.setAttribute("aria-expanded", String(open));
}

function foldRail() {
  toggleRail(false);
}

function onKey(event) {
  /* Escape, and nothing else. There are no keyboard shortcuts on this
     page: every command is a button and a line you can type, and a key
     that does something a reader cannot see is a key nobody finds. What
     the KEYBOARD still answers is what a screen advertises in its own
     footer — the arrows in a list, `/` for its filter, enter to take a
     row — and those belong to the screen, not to the document. */
  if (event.key === "Escape") {
    // The one on TOP, which is the one holding focus — `dialog[open]`
    // in markup order would close whatever happens to be written first.
    const open = $$("dialog[open]");
    const dialog = open.find((d) => d.contains(document.activeElement)) ?? open.at(-1);
    if (!dialog) {
      foldRail();
      return;
    }
    event.preventDefault();
    /* The depths inside a popup — a filter, a field editor, a confirm —
       claim Esc before it reaches here. What is left is
       the outermost level: the popup itself. */
    dialog.close();
    return;
  }
}

start();
boot();
