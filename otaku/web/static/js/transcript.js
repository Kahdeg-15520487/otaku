/* How a turn looks — stored or arriving.

   Bodies cross from the backend VERBATIM. Where a paragraph breaks, what
   a slash token is drawn as, and where the caret rides are decided here
   and nowhere else; nothing in this file rewrites the text itself.

   The page draws the story as a book draws one: the reply is prose in
   the flow, and a played line is a centred interjection under a mono
   rubric — the same meaning as the terminal's `>` band, in this
   medium's shape. Waiting and streaming are ONE state: the caret holds
   the answer's place and text grows in front of it, with a status line
   under it while it runs.

   Three kinds of line are not the story and never read as it: the
   model's thinking, the verbose stats the terminal prints after a
   reply, and a failure. Each has its own voice.

   It renders the undo/regen bar but does not know what those do: the
   buttons carry `data-turn`, and whoever owns commands listens. That
   keeps the transcript a drawing, not a controller. */

import * as api from "./api.js";
import { $, $$, element, span } from "./dom.js";
import { typeset } from "./prose.js";
import { tell, working } from "./status.js";
import { isToken } from "./table.js";

const transcript = $(".otk-transcript");
const stop = $("[data-stop]");
const send = $("[data-send]");

// The reply in flight, so Stop has something to stop — and a promise
// that keeps until it is over, for whoever asked it to stop.
let arriving = null;
let settled = Promise.resolve();

// One turn at a time, as in the terminal: a session plays one line, and
// the composer waits for it.
let playing = false;

// The ordinal the NEXT drawn turn takes — the rubric's number, counted
// the way the story browser counts messages.
let ordinal = 0;

export const isPlaying = () => playing;

// ---------- what is on screen ----------

export function showTurns(turns, { keepPlace = false } = {}) {
  /* `keepPlace` is for a redraw the reader did not ask to be moved by —
     an undo, a regenerate: the turns change, the scroll does not, and
     what was taken away simply leaves the space it was in. */
  ordinal = turns.length;
  const drawn = turns.map((turn, i) => drawTurn(turn, i + 1));
  if (keepPlace) {
    holdSpace(() => transcript.replaceChildren(...drawn));
    showTurnBar();
    return;
  }
  release();
  transcript.replaceChildren(...drawn);
  showTurnBar();
  toBottom({ force: true });
}

export function clear() {
  transcript.replaceChildren();
}

/** Send while the box is the reader's, Stop while the model has it. */
function turnOver(streaming) {
  if (send) send.hidden = streaming;
  if (stop) stop.hidden = !streaming;
}

/** Give up on the reply that is arriving, and answer when it is over.
    The connection going away IS the backend's cancel-and-keep door —
    the same one a closed tab goes through — so what has streamed stays
    in the story. */
export function stopPlaying() {
  arriving?.abort();
  return settled;
}

/* ---------- holding the reader's place ----------

   Taking turns away shortens the flow, and a shorter flow moves under
   whoever is reading it: the browser clamps a scroll position that no
   longer exists and everything above jumps. So the space is held open —
   an empty block after the last turn, exactly as tall as the position
   needs to stay legal and not one pixel taller:

       held = (where we are) + (what we can see) - (what is left)

   which is zero the moment the flow grows back into it, and never more
   than one screenful however much is taken away. A BLOCK rather than
   padding on the flow itself: padding is part of the scroller's own
   box, and a scroller that grows takes the page with it.

   The space is given back as new text fills it, and once it is gone the
   flow follows the text down again — for a reader who was at the tail
   when they asked for it. `overflow-anchor` is off in the stylesheet, so
   Chrome and Firefox do not fight this with anchoring of their own;
   nothing here needs a feature Safari lacks. */

let holdAt = null; // the scroll position being protected, null when none

function holdSpace(change) {
  const top = transcript.scrollTop;
  change();
  holdAt = top;
  reserve();
}

function reserve() {
  if (holdAt === null) return;
  const gap = room();
  gap.style.height = "0px";
  const needed = Math.max(0, holdAt + transcript.clientHeight - transcript.scrollHeight);
  gap.style.height = `${needed}px`;
  transcript.scrollTop = holdAt;
  // Caught up: the flow is tall enough to be read where it was, and
  // holding it does nothing but keep a scrollbar longer than the story.
  if (!needed) release();
}

function release() {
  holdAt = null;
  room().style.height = "0px";
}

function room() {
  let gap = $(".otk-gap", transcript);
  if (!gap) {
    gap = element("div", "otk-gap");
    gap.setAttribute("aria-hidden", "true");
  }
  // `replaceChildren` takes it with the turns; it belongs last, always.
  if (gap.parentElement !== transcript || gap.nextSibling) transcript.append(gap);
  return gap;
}

function atTail() {
  const gap = $(".otk-gap", transcript);
  const empty = gap ? gap.getBoundingClientRect().height : 0;
  // The held space is not story: a reader sitting above it is at the
  // tail of what there is to read.
  return transcript.scrollHeight - empty - transcript.scrollTop - transcript.clientHeight < 120;
}

function toBottom({ force = false } = {}) {
  /* Only when the reader is already there. A story being read further up
     must not be yanked down because a turn was taken back or a reply was
     re-run — the two things that change what is BELOW the fold without
     the reader asking for a new line. `force` is for the one case that
     is the reader asking: a line they just sent. */
  if (force || atTail()) transcript.scrollTop = transcript.scrollHeight;
}

// ---------- drawing a turn ----------

function drawTurn(turn, position) {
  if (turn.role === "user") {
    const article = element("article", "otk-turn");
    const rubric = element("span", "otk-turn__rubric", `◆ ${position} · you`);
    const line = element("p", "otk-turn__body");
    line.append(...withSlashTokens(turn.body));
    article.append(rubric, line);
    return article;
  }
  const article = element("article", "otk-reply");
  drawProse(article, turn.body);
  return article;
}

function withSlashTokens(line) {
  /* The typed line, with its command words picked out — as the terminal
     highlights them in the played block. Split on whitespace runs so the
     line comes back exactly as it went in, spaces and all. */
  return line.split(/(\s+)/).map((piece) => {
    if (!isToken(piece)) return document.createTextNode(piece);
    return element("span", "otk-slash", piece);
  });
}

function drawProse(article, text, { streaming = false } = {}) {
  /* The reply as it stands, re-typeset from the whole text rather than
     appended to: a paragraph break arrives mid-stream like any other
     character, and only the whole text knows where the breaks are. */
  const paragraphs = text.split(/\n\s*\n/).filter((part) => part.trim());
  const drawn = $$(".otk-prose", article);
  paragraphs.forEach((paragraph, i) => {
    const p = drawn[i] ?? article.insertBefore(element("p"), $(".otk-generating__status", article));
    // Two shapes of the same accent: a paragraph that is nothing but
    // speech takes it whole, and a mixed one takes it a run at a time.
    const { spoken, nodes } = typeset(paragraph.trim());
    p.className = spoken ? "otk-prose otk-prose--dialogue" : "otk-prose";
    p.replaceChildren(...nodes);
  });
  // The caret rides the end of what has arrived — the one moving thing
  // on the page, and the only one actually happening.
  $(".otk-caret", article)?.remove();
  if (streaming) {
    const caret = element("span", "otk-caret");
    caret.setAttribute("aria-hidden", "true");
    ($$(".otk-prose", article).at(-1) ?? article).append(caret);
  }
}

function showTurnBar() {
  /* undo and regenerate belong to the last exchange and to no other —
     the terminal offers them for the same one turn. They live under the
     PROMPT, not under the turn: they are what you do next, and next is
     where the cursor is. Drawn once in the markup, so this only decides
     whether there is anything to act on. */
  const turns = $$(".otk-turn, .otk-reply", transcript).length;
  /* Both act on the last exchange, so both are off when there is no
     exchange to act on. Regenerate answers mid-reply as well — it means
     "not this one" and takes the same door Stop does; undo cannot,
     because the turn it would take back has not landed yet. */
  const undo = $("[data-turn='undo']");
  const regen = $("[data-turn='regen']");
  undo?.setAttribute("aria-disabled", String(!turns || playing));
  regen?.setAttribute("aria-disabled", String(!turns));
}

/* ---------- a turn arriving ----------

   One reply, told in three parts: `beginTurn` opens the block the reply
   will land in, one drawer per event kind fills it (the same closed
   union `web.api.event` writes), and `endTurn` settles it — whatever
   ended it. `play` below is only the order of those. */

/** Play a line and draw the reply as it streams. `line` is null for a
    regenerate, where the prompt is already on screen and in the store. */
export async function play(line, { regenerate = false } = {}) {
  // One turn at a time. Without this a second play starts while the
  // first is in flight, and the first to finish unlocks the composer
  // for both — leaving prose on screen that the store never took.
  if (playing) return;
  const turn = beginTurn(regenerate);
  let refused = null;
  try {
    const answer = await api.play(line ?? "", { regenerate, signal: arriving.signal });
    // A line that is not valid syntax never becomes a stream: the usage
    // sentence comes back instead, and the story is untouched.
    if (answer.refused) {
      refused = answer.refused;
      // A refused regenerate keeps its reply: the backend promised the
      // story is untouched, so the screen has to say the same.
      if (regenerate) showTurns(await api.turns(), { keepPlace: true });
      return;
    }
    for await (const happened of answer.events) {
      draw(turn, happened);
    }
  } catch (e) {
    // Stopping is not failing: the reader asked for the socket to go
    // away, and what streamed before it did is already in the story.
    if (e?.name !== "AbortError") throw e;
  } finally {
    endTurn(turn);
    // Said AFTER the turn is settled, or the cleanup's own clearing
    // would sweep the refusal away before anyone read it.
    if (refused) tell(refused, "otk-error");
  }
}

function beginTurn(regenerate) {
  /* A played line is the reader asking for something new at the bottom.
     A regenerate is not: it redraws what is already on screen, into the
     space the old take was read in — and only once it has FILLED that
     space does it follow the text down, and then only for a reader who
     was at the tail to begin with. Measured now, before anything
     moves. */
  const tail = atTail();
  playing = true;
  arriving = new AbortController();
  let over;
  settled = new Promise((resolve) => (over = resolve));
  turnOver(true);
  tell("");
  // Stopping a reply is the composer's own button, right where it was
  // asked for — so the status line says only that something is running.
  working(true);
  showTurnBar();
  const article = element("article", "otk-reply otk-generating is-streaming");
  /* The transcript is a polite live region, and a reply rewrites its
     text several times a second: without this a screen reader is asked
     to re-announce a growing paragraph forty times and says nothing
     useful. `aria-busy` is the standard answer — hold the subtree, and
     announce it once when it settles. */
  article.setAttribute("aria-busy", "true");
  /* Waiting and writing are ONE state: the caret holds the answer's
     place from the first moment, and text grows in front of it. Under
     it, the line that says the model has the turn and for how long. */
  const held = element("p", "otk-prose");
  const caret = element("span", "otk-caret");
  caret.setAttribute("aria-hidden", "true");
  held.append(caret);
  /* The rule runs BEHIND the words, which sit on paper over it — so the
     creep never appears out of nowhere at an edge. */
  const state = element("span", "otk-generating__text", "waiting");
  const elapsed = element("span", "otk-generating__text otk-generating__elapsed", "0.0s");
  const status = element("div", "otk-generating__status");
  status.setAttribute("aria-hidden", "true");
  status.append(element("span", "otk-generating__rule"), state, elapsed);
  article.append(held, status);
  const started = Date.now();
  const ticking = setInterval(() => {
    elapsed.textContent = `${((Date.now() - started) / 1000).toFixed(1)}s`;
  }, 100);
  /* A regenerate takes the standing reply off the screen NOW, before the
     request is even away: the reader asked for another take, and the one
     they are replacing must not sit there while the model thinks. The
     backend validates a regenerate eagerly, so a refusal comes back
     before any of it is lost — and `showTurns` puts the story back as
     the store has it. */
  if (regenerate) holdSpace(dropLastReply);
  showTurnBar();
  return { article, status, state, ticking, over, tail, thinking: null, prose: "" };
}

function draw(turn, happened) {
  // A regenerate sends no Recorded — its prompt is already on screen —
  // so the reply's own block joins the flow at the first sign of it, or
  // it would stream into nothing.
  if (!turn.article.isConnected) transcript.append(turn.article);
  DRAW[happened.type]?.(turn, happened);
  // What arrives goes into the space the old take was read in.
  reserve();
  follow(turn);
}

// One drawer per event kind — `web.api.event`'s closed union, drawn.
const DRAW = {
  recorded(turn, happened) {
    ordinal += 1;
    transcript.insertBefore(drawTurn(happened.turn, ordinal), turn.article);
  },
  thinking(turn, happened) {
    if (!turn.thinking) {
      turn.thinking = element("p", "otk-thinking", "(thinking) ");
      turn.article.prepend(turn.thinking);
    }
    turn.thinking.textContent += happened.text;
    turn.state.textContent = "thinking";
  },
  text(turn, happened) {
    turn.prose += happened.text;
    turn.state.textContent = "writing";
    drawProse(turn.article, turn.prose, { streaming: true });
  },
  declined(turn, happened) {
    turn.article.append(failure("The model declined", happened.reason));
  },
  failed(turn, happened) {
    turn.article.append(failure("The reply stopped", happened.reason));
  },
  done(turn, happened) {
    // The stats line the terminal prints after a reply, verbatim — off
    // unless the reader asked for it (`/set verbose`).
    if (happened.stats) turn.article.append(element("p", "otk-verbose", happened.stats));
  },
};

function failure(label, reason) {
  /* A failure is not a turn and never reads as the story: its own rule,
     its own voice, and the two doors out of it. The LABEL names the
     state (the medium's own word); the sentence under it is the
     backend's, unchanged. */
  const box = element("div", "otk-error");
  const actions = element("div", "otk-error__actions");
  const again = element("button", "otk-btn", "Try again");
  again.type = "button";
  again.dataset.turn = "regen";
  const other = element("button", "otk-btn", "Choose another model");
  other.type = "button";
  other.dataset.command = "/model";
  actions.append(again, other);
  box.append(
    span("otk-error__label", label),
    element("p", "otk-error__body", reason),
    actions,
  );
  return box;
}

function endTurn(turn) {
  // Whatever ended it — the last event, the reader's Stop, or a
  // connection that went away mid-reply — the turn stops looking like
  // it is still arriving.
  playing = false;
  arriving = null;
  clearInterval(turn.ticking);
  turn.over();
  turnOver(false);
  working(false);
  // Whatever the page had to say about the last attempt is over with
  // the turn it was about.
  tell("");
  /* The status row STAYS, hidden: it keeps its height, so the moment a
     reply lands nothing above it moves. */
  turn.article.classList.add("otk-generating--idle");
  turn.article.classList.remove("is-streaming");
  turn.article.setAttribute("aria-busy", "false");
  $(".otk-caret", turn.article)?.remove();
  // The paragraph that held the answer's place, when nothing came to
  // fill it: an empty line is not a reply and must not stand as one.
  for (const p of $$(".otk-prose", turn.article)) if (!p.textContent) p.remove();
  // A reply that never arrived leaves no empty block behind.
  if (!turn.prose && !$(".otk-error, .otk-verbose, .otk-thinking", turn.article)) {
    turn.article.remove();
  } else if (turn.article.isConnected && turn.prose) {
    /* The reply landed: the story is one turn longer than the rubric
       counted at the recorded event. TEXT is the test, not the block —
       a declined or failed attempt keeps its block to say so but stores
       no message (`backend.api.play._land_reply` records a reply row
       only when some text arrived), and counting it would number every
       later turn one too high. */
    ordinal += 1;
  }
  showTurnBar();
  follow(turn);
}

function follow(turn) {
  // While space is held the flow does not move: the new text is going
  // into the place the reader is already looking at. Once it has filled
  // that space, the flow follows it down — for whoever was at the tail
  // when they asked for it.
  if (holdAt === null && turn.tail) toBottom({ force: true });
}

/* Take the standing reply off the screen, so the fresh take streams in
   its place rather than under it. */
function dropLastReply() {
  const last = [...$$(".otk-turn, .otk-reply", transcript)].pop();
  if (last && last.classList.contains("otk-reply")) {
    last.remove();
    ordinal -= 1;
  }
}
