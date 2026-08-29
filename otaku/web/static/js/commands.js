/* What a row of the contents opens, and the few doors that are a call
   rather than a screen.

   Every one of these is reached by a BUTTON — nothing here composes a
   command line for the far end to parse. `SCREENS` is keyed by the token
   the contents rail carries, because a rail row and a screen are one
   thought; what each one then asks of otaku is an endpoint, named in
   `api.js`. */

import * as api from "./api.js";
import { ask, closeAll, popups } from "./browser.js";
import { $ } from "./dom.js";
import { openHelp } from "./help.js";
import { openSettings } from "./settings.js";
import { openModels } from "./models.js";
import { openBalance, openContext, openInfo, openUsage } from "./reports.js";
import { disconnected, landed, refresh, watchExtraction } from "./shell.js";
import { openStories } from "./stories.js";
import { openStory } from "./story.js";
import { tell } from "./status.js";
import { clear, isPlaying, play, stopPlaying } from "./transcript.js";
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
  "/new": newStory,
  "/fork": () =>
    confirmed({
      title: "Fork this story?",
      body: "A copy from here on. The original stays as it is, and play continues in the copy.",
      action: "Fork",
      run: async () => {
        const story = (await api.facts()).story_id;
        if (story === null) return tell(_NO_STORY.fork, "otk-error");
        const { notice } = await api.fork(story);
        await landed(notice, { redraw: "always" });
      },
    }),
  /* The story dossier answers three commands, one tab each — the bare
     token opens it there; `/system some text` is answered by the
     backend, exactly as `/model` and `/model x/y` divide. */
  "/system": () => openStory({ tab: "premise", allStories: backToStories }),
  "/lore": () => openStory({ tab: "scenes", allStories: backToStories }),
  "/cast": () => openStory({ tab: "cast", allStories: backToStories }),
  "/model": openModels,
  "/set": openSettings,
  "/context": openContext,
  "/usage": openUsage,
  "/balance": openBalance,
  "/info": openInfo,
  "/help": () => openHelp(),
  "/import": importStory,
  "/card": importCard,
  "/export": exportStory,
  "/extract": extractNow,
  "/undo": undo,
  "/regen": regenerate,
  "/last": () => refresh(),
  "/clear": () => clear(),
  // A tab is not the session: closing one must not stop a server the
  // reader may be using from another, so /bye says where the exit is.
  "/bye": () => tell("Close the tab. The server stops in the terminal."),
};

export async function run(token) {
  /* One row of the contents, opened. The token is a UI key — what the
     rail's button carries — and never a line anybody typed. */
  try {
    const screen = SCREENS[token];
    if (screen) await screen();
    else console.warn("otaku: no screen for", token);
  } catch (e) {
    // The reader gets the sentence; the console gets the stack, because
    // a TypeError inside a screen is a bug, not an answer.
    console.error(e);
    tell(String(e.message ?? e), "otk-error");
  }
}

/** Where a dossier's back button lands when no story browser waits
    underneath it: the browser, positioned on the story it came from. */
const backToStories = (storyId) => openStories("", { selectId: storyId });

/** The contents row that is not a command: the open story's messages,
    which live on the dossier the way its scenes and cast do. A UI door,
    not a token — `app.js` wires the button here so the dossier stays
    reachable without inventing a command nobody typed. */
export async function openMessages() {
  try {
    await openStory({ tab: "messages", allStories: backToStories });
  } catch (e) {
    console.error(e);
    tell(String(e.message ?? e), "otk-error");
  }
}

/** Whether a command carried by a panel's own chrome KEEPS that panel.
    `app.js` closes a popup before running a command in its header,
    because the answer usually lands in the flow behind it — but two
    kinds of row must be left where they were fired from: one that asks
    a question (a question cancelled has no answer, and closing first
    would take the reader out of the screen for nothing), and one whose
    whole result belongs to that screen — an import that adds a row to
    the list you are reading, an export that saves a file and changes
    nothing. */
export function keepsScreen(token) {
  return ["/new", "/fork", "/extract", "/import", "/export"].includes(token);
}

async function newStory() {
  /* A new story is one question with an optional answer: what to call
     it. Left empty, the listing names it from its first rollup — which
     is the sentence under the field. */
  const dialog = $('dialog[data-dialog="new-story"]');
  const field = $("input", dialog);
  const choice = await ask("new-story", () => (field.value = ""));
  if (choice !== "start") return;
  closeAll();
  const { notice } = await api.newStory(field.value.trim());
  await landed(notice, { redraw: "always" });
}

async function importStory() {
  /* The imported story lands in the library the reader is looking at,
     so the list is asked again and left on what just arrived — the
     screen a reader imported FROM is the screen that must show it. */
  await importDocument();
  if (popups.get("/stories")?.open) {
    const facts = await api.facts();
    await openStories("", { selectId: facts.story_id });
  }
}

async function confirmed({ title, body, note = "", action, cancel = "Cancel", run }) {
  /* One question, one button that answers it. The dialog is the ask
     family's plainest shape and its words are set here, because what a
     command is about to do to the story on screen is the page's to say
     — the same way the delete confirm says what a delete takes. */
  const choice = await ask("confirm", (dialog) => {
    $("[data-title]", dialog).textContent = title;
    $(".otk-dialog__body", dialog).textContent = body;
    // A second line, for a question whose answer has a consequence
    // worth spelling out; hidden for the plain ones.
    const aside = $("[data-note]", dialog);
    aside.textContent = note;
    aside.hidden = !note;
    $('[data-choice="confirm"]', dialog).textContent = action;
    $('[data-choice="cancel"]', dialog).textContent = cancel;
  });
  if (choice !== "confirm") return;
  // Now the screens go: the story is about to change under them, and the
  // sentence that says so belongs in the flow.
  closeAll();
  await run();
}

/** Play a line as story, reporting a lost connection the one way the
    page has to report one. */
export async function playLine(line) {
  try {
    await play(line);
    /* A played line is a write like any other, and the runhead is drawn
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
  const answer = await api.undo();
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

/* What the backend says when there is no story to act on. COPIED,
   because the page cannot ask: these endpoints address a story by its
   id, and with no story there is no id to put in the path. Their homes
   are `backend.api.stories.fork` and `backend.api.lore.extract` — a
   sentence that changes there changes here. */
const _NO_STORY = {
  fork: "Nothing to fork yet — send a message first.",
  extract: "No story yet — send a message first.",
};

async function extractNow() {
  /* A pass is minutes of model time, so the question says so before it
     starts one — and says what happens if the reader waits instead,
     because waiting is the normal way this runs. */
  const facts = await api.facts();
  const opened = facts.story_id == null ? null : await api.story(facts.story_id).catch(() => null);
  const unread = opened?.unread ?? 0;
  await confirmed({
    title: "Read them now?",
    body:
      (unread
        ? `${unread} ${unread === 1 ? "message has" : "messages have"} not been read into scenes and cast. `
        : "Everything played has been read already. ") +
      "Reading asks the model for a summary, a history and a journal per character — it can take a minute or two.",
    note: "Otherwise it happens on its own, five minutes after you stop typing.",
    action: "Read now",
    cancel: "Wait",
    run: () =>
      facts.story_id === null
        ? tell(_NO_STORY.extract, "otk-error")
        : extract(facts.story_id),
  });
}

async function extract(story) {
  const { notice, watching } = await api.extract(story);
  closeAll();
  tell(notice);
  if (watching) watchExtraction(story);
}
