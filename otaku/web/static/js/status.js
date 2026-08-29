/* The one line otaku speaks in: the reserved row at the foot of the
   contents. Everything the app has to SAY arrives here — what a command
   answered, what the background worker is doing, that the server went
   away — because the transcript is the story, and a story is only what
   was played into it.

   The line is one component with three parts and never moves: a lamp
   that says what the SESSION is doing, the sentence, and at most one
   action. It holds its height when it has nothing to say, so nothing on
   the page jumps.

   A leaf on purpose: it knows how to draw a line and nothing about what
   otaku is, so every module that has something to say can reach it
   without reaching for a screen. */

import { $ } from "./dom.js";

const line = $(".otk-status");
const lamp = $(".otk-status__lamp", line);
const text = $(".otk-status__text", line);
const action = $(".otk-status__action", line);

/* What the lamp is saying, most severe first. `offline` outranks
   everything (nothing else is true while otaku is gone), `working`
   outranks the resting state, and `idle` is the state before the first
   answer — a session nobody has heard from yet. */
let gone = false;
let busy = false;
let heard = false;

/* What the line reads when otaku has nothing to say. A reserved row that
   is blank looks broken; a word there says the session is up and waiting.
   It is about the MEDIUM — the state of the page, not an answer — which
   is why it is the frontend's own and not a backend sentence. */
const _RESTING = "Ready";

export function tell(sentence, kind = "") {
  /* What otaku just said. `kind` marks a refusal, which reads as one —
   the flag is the caller's, and the WORDING is always the backend's. */
  if (!text) return;
  text.textContent = sentence || _RESTING;
  // The line is one row and cuts with an ellipsis, so the whole of it
  // has to be somewhere: hovering it is where.
  text.title = sentence || _RESTING;
  line.classList.toggle("otk-status--said", Boolean(sentence) && kind !== "otk-error");
  line.classList.toggle("otk-status--error", Boolean(sentence) && kind === "otk-error");
}

/** What is on the line right now — for the beat, which takes its own
    sentence down when the pass it was about is over, and leaves
    anything said since alone. The resting word is not something said,
    so it reads as nothing. */
export function told() {
  const said = text?.textContent ?? "";
  return said === _RESTING ? "" : said;
}

/** The session is answering: the lamp lives from the first answer on. */
export function reached() {
  heard = true;
  paint();
}

/** Something is running — a reply, or a pass. `stop` is what to call if
    it can be given up on; without one the line says only that it runs. */
export function working(running, stop = null) {
  busy = running;
  offer(running && stop ? "stop" : "", stop);
  paint();
}

/** otaku stopped answering. The line says so and offers nothing: there
    is no button that can bring a stopped server back, and the page picks
    the session up again by itself the moment it answers. */
export function offline(lost) {
  gone = lost;
  if (!busy) offer("", null);
  paint();
}

function offer(label, onClick) {
  if (!action) return;
  action.textContent = label;
  action.hidden = !label;
  action.onclick = label ? onClick : null;
}

function paint() {
  const state = gone ? "offline" : busy ? "working" : heard ? "" : "idle";
  for (const name of ["offline", "working", "idle"]) {
    line.classList.toggle(`otk-status--${name}`, state === name);
  }
}

// The row is reserved from the first paint, so it says the resting word
// from the first paint too — an empty reserved row reads as a fault.
tell("");
