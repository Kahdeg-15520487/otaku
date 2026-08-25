/* What a command does on this side — the dispatch half, routing by the
   language in `table.js` exactly as the terminal's bindings route by
   `backend.commands`.

   Every command is reachable two ways and both come here: a click on a
   rail button, and a line typed into the composer. A BARE token opens
   its screen; the same token with an argument is answered by the backend
   — `/model` opens the picker, `/model ollama/x` switches — exactly as
   the terminal reads them.

   SCREENS is this frontend's half of the shared table, as
   `terminal.chat.bindings._INTERACTIVE` is the terminal's: everything
   the backend does NOT answer with a sentence must have a row here, and
   `checkCoverage` proves it at boot rather than leaving a button dead. */

import * as api from "./api.js";
import { ask, closeAll } from "./browser.js";
import { $ } from "./dom.js";
import { openHelp } from "./help.js";
import { openSettings } from "./settings.js";
import { openLore } from "./lore.js";
import { openModels } from "./models.js";
import { openBalance, openContext, openInfo, openUsage } from "./reports.js";
import { disconnected, landed, refresh, watchExtraction } from "./shell.js";
import { openStories } from "./stories.js";
import { openSystem } from "./system.js";
import { allSpecs, answered, rawArgument, specFor } from "./table.js";
import { clear, isPlaying, play, stopPlaying, tell } from "./transcript.js";
import { exportStory, importCard, importDocument } from "./transfer.js";

const SCREENS = {
  "/stories": openStories,
  /* The two that make a story are asked about first. Both are one click
     from the story you are reading, neither says what it did to it, and
     `/new` in particular reads as "close this" — so the page asks, the
     way it asks before a delete. A TYPED `/new TITLE` or `/fork TITLE`
     carries an argument and goes straight to the backend, as every
     other command with one does: the reader who spelled it out has
     already said yes. */
  "/new": () =>
    confirmed({
      title: "New story",
      body: "Do you want to start a new story?",
      action: "New story",
      line: "/new",
    }),
  "/fork": () =>
    confirmed({
      title: "Fork this story?",
      body: "A copy from here on. The original stays as it is, and play continues in the copy.",
      action: "Fork",
      line: "/fork",
    }),
  // The bare token opens the screen; `/system some text` is answered by
  // the backend, exactly as `/model` and `/model x/y` divide.
  "/system": openSystem,
  "/lore": () => openLore("scenes"),
  "/cast": () => openLore("cast"),
  "/model": openModels,
  "/set": openSettings,
  "/context": openContext,
  "/usage": openUsage,
  "/balance": openBalance,
  "/info": openInfo,
  "/help": () => openHelp(),
  "/import": importDocument,
  "/card": importCard,
  "/export": exportStory,
  "/extract": () =>
    confirmed({
      title: "Extract now",
      body: "Do you want to read the recent messages into scenes and cast now?",
      action: "Extract now",
      run: extract,
    }),
  "/undo": undo,
  "/regen": regenerate,
  "/last": () => refresh(),
  "/clear": () => clear(),
  // A tab is not the session: closing one must not stop a server the
  // reader may be using from another, so /bye says where the exit is.
  "/bye": () => tell("Close the tab. The server stops in the terminal."),
};

export function checkCoverage() {
  /* The terminal would raise a KeyError for a command with no handler.
     The page cannot, so it says so where a developer will see it — and
     "has no screen here yet" becomes unreachable, which is the point. */
  const missing = allSpecs()
    .filter((row) => row.kind !== "syntax" && !SCREENS[row.token] && !answered(row.token))
    .map((row) => row.token);
  if (missing.length) console.warn("otaku: no handler for", missing.join(", "));
}

export async function run(line) {
  try {
    const spec = specFor(line);
    const argument = rawArgument(line, spec);
    /* A screen opens for the bare token; the same token WITH an argument
       goes to the backend when the backend answers it — `/model` opens
       the picker, `/model ollama/x` switches, exactly as the terminal
       reads them. Only a row the backend cannot answer keeps its screen
       for both forms, which is how `/last 3` and `/card NAME` arrive. */
    const answers = spec && answered(spec.token);
    const screen = argument && answers ? null : SCREENS[spec?.token ?? line.trim()];
    if (screen) {
      await screen(argument);
      return;
    }
    // Everything else — wired rows and unknown tokens alike — is the
    // backend's to answer: an unknown line comes back as the shared
    // sentence (`backend.commands.unknown_notice`), marked refused, so both
    // frontends refuse a typo with the same words.
    const { notice } = await api.runCommandLine(line);
    await landed(notice);
  } catch (e) {
    // The reader gets the sentence; the console gets the stack, because
    // a TypeError inside a screen is a bug, not an answer.
    console.error(e);
    tell(String(e.message ?? e), "otk-error");
  }
}

/** Whether a command asks before it acts. A screen that opens a question
    of its own must be left the screen it was called FROM: `app.js` closes
    a popup before running a command carried in its header, because the
    answer lands in the flow behind it — but a question cancelled has no
    answer, and closing first would take the reader out of the browser
    they were reading for nothing. */
export function asksFirst(token) {
  return token === "/new" || token === "/fork" || token === "/extract";
}

async function confirmed({ title, body, action, line, run }) {
  /* One question, one button that answers it. The dialog is the ask
     family's plainest shape and its words are set here, because what a
     command is about to do to the story on screen is the page's to say
     — the same way the delete confirm says what a delete takes. */
  const choice = await ask("confirm", (dialog) => {
    $("[data-title]", dialog).textContent = title;
    $(".otk-dialog__body", dialog).textContent = body;
    $('[data-choice="confirm"]', dialog).textContent = action;
  });
  if (choice !== "confirm") return;
  // Now the screens go: the story is about to change under them, and the
  // sentence that says so belongs in the flow.
  closeAll();
  if (run) {
    await run();
    return;
  }
  const { notice } = await api.runCommandLine(line);
  await landed(notice, { redraw: "always" });
}

/** Play a line as story, reporting a lost connection the one way the
    page has to report one. */
export async function playLine(line) {
  try {
    await play(line);
    /* A played line is a write like any other, and the header is drawn
       from facts that just changed: the first line of a session makes
       the story that "No story yet" was standing in for, and every line
       after it moves the count. No notice — the reply IS the answer —
       and no redraw unless the ground moved, which `landed` decides. */
    await landed("");
  } catch {
    disconnected();
  }
}

// ---------- the rows that are not one call ----------

/* Both doors to these — the turn bar and the composer — come through
   here, so the refusal is written once. Taking a turn back while the
   next one is still arriving would take back the WRONG one: the request
   queues behind the reply and lands after it. */

export function midReply() {
  if (!isPlaying()) return false;
  // Under the prompt, where the reader is: this is about the box, not
  // about the scene, and the story must not carry a line nobody played.
  tell("Wait for the reply to finish, or stop it.");
  return true;
}

async function undo() {
  if (midReply()) return;
  /* The notice is not shown: the exchange coming off the screen IS the
     answer, and a line saying so would be the third thing the reader
     reads about a turn they can see is gone. A refusal — nothing to
     undo — still speaks, under the prompt, and it is the FLAG that says
     so: the page never reads the wording. */
  const answer = await api.runCommandLine("/undo");
  await landed("", { redraw: "always", keepPlace: true });
  if (answer.refused) tell(answer.notice);
}

async function regenerate() {
  /* Mid-reply, regenerate means "not this one, try again" — the same
     thing `/regen` means in the terminal, where it cancels the stream
     and re-runs the prompt. Stop is the same door, so this takes it and
     waits for the socket to be over before asking for the next take. */
  if (isPlaying()) await stopPlaying();
  // The standing reply becomes a sibling and the fresh take streams in
  // its place; `play` takes the old one off the screen once the request
  // is accepted, so a refusal leaves the story exactly as it was.
  try {
    await play(null, { regenerate: true });
  } catch {
    disconnected();
  }
}

async function extract() {
  const { notice, watching } = await api.act("extract", {});
  closeAll();
  tell(notice);
  if (watching) watchExtraction();
}
