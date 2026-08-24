/* How a turn looks — stored or arriving.

   Bodies cross from the backend VERBATIM. Where a paragraph breaks, what
   a slash token is drawn as, and where the caret rides are decided here
   and nowhere else; nothing in this file rewrites the text itself.

   It renders the undo/regen bar but does not know what those do: the
   buttons carry `data-turn`, and whoever owns commands listens. That
   keeps the transcript a drawing, not a controller. */

import * as api from "./api.js";
import { $, $$, element } from "./dom.js";
import { isToken } from "./table.js";

const transcript = $(".otk-transcript");
const said = $(".otk-composer__said");
const stop = $("[data-stop]");
const send = $("[data-send]");

// The reply in flight, so Stop has something to stop — and a promise
// that keeps until it is over, for whoever asked it to stop.
let arriving = null;
let settled = Promise.resolve();

// One turn at a time, as in the terminal: a session plays one line, and
// the composer waits for it.
let playing = false;

export const isPlaying = () => playing;

// ---------- what is on screen ----------

export function showTurns(turns, { keepPlace = false } = {}) {
  /* `keepPlace` is for a redraw the reader did not ask to be moved by —
     an undo, a regenerate: the turns change, the scroll does not, and
     what was taken away simply leaves the space it was in. */
  if (keepPlace) {
    holdSpace(() => transcript.replaceChildren(...turns.map(drawTurn)));
    showTurnBar();
    return;
  }
  release();
  transcript.replaceChildren(...turns.map(drawTurn));
  showTurnBar();
  toBottom({ force: true });
}

export function clear() {
  transcript.replaceChildren();
}

/** What is on the say line right now — for the beat, which takes its own
    sentence down when the pass it was about is over, and leaves anything
    said since alone. */
export function told() {
  return said?.textContent ?? "";
}

/** Everything otaku has to SAY, as opposed to everything it played: a
    command's answer, a refusal, a report, a failure. All of it belongs
    under the prompt — the transcript is the story, and a story is what
    was played into it. `kind` marks a refusal, which reads red.

    It clears itself the moment the reader types again, or the next turn
    begins: a sentence about the last line is over when the next one is. */
export function tell(text, kind = "") {
  if (!said) return;
  said.textContent = text ?? "";
  said.classList.toggle("is-error", Boolean(text) && kind === "otk-error");
}

/** Send while the box is the reader's, Stop while the model has it. */
function turnOver(streaming) {
  if (send) send.hidden = streaming;
  if (stop) stop.hidden = !streaming;
  if (send) send.disabled = streaming;
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

function drawTurn(turn) {
  const article = element("article", "otk-turn");
  if (turn.role === "user") {
    article.classList.add("otk-turn--user");
    const line = element("p", "otk-turn__typed");
    line.append(...withSlashTokens(turn.body));
    article.append(line);
    return article;
  }
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

/* An opening quote and the marks that may answer it. The rule is the
   terminal's, copied (`otaku/terminal/tty/typography.py`, where the
   whole convention including the dialogue dash lives): `“` both opens
   English speech and closes German, the straight quote closes itself,
   and `„` takes either curly mark because the strict pairing is rarely
   typed. */
const _CLOSERS = { "«": "»", "“": "”", "„": "“”", '"': '"' };

function speech(paragraph) {
  /* The paragraph as spoken and unspoken runs, decided forward-only at
     the opening mark — the same way the terminal decides, because a
     reply arrives a character at a time and there is nothing ahead to
     read. A quote left open is spoken to the end: mid-stream it is a
     line still arriving. */
  const runs = [];
  let plain = "";
  let quote = null;
  for (const ch of paragraph) {
    if (quote) {
      quote.text += ch;
      if (quote.closers.includes(ch)) {
        runs.push({ spoken: true, text: quote.text });
        quote = null;
      }
      continue;
    }
    if (_CLOSERS[ch]) {
      if (plain) runs.push({ spoken: false, text: plain });
      plain = "";
      quote = { text: ch, closers: _CLOSERS[ch] };
      continue;
    }
    plain += ch;
  }
  if (quote) runs.push({ spoken: true, text: quote.text });
  else if (plain) runs.push({ spoken: false, text: plain });
  return runs;
}

function drawProse(article, text, { streaming = false } = {}) {
  /* The reply as it stands, re-typeset from the whole text rather than
     appended to: a paragraph break arrives mid-stream like any other
     character, and only the whole text knows where the breaks are. */
  const paragraphs = text.split(/\n\s*\n/).filter((part) => part.trim());
  const drawn = $$(".otk-prose", article);
  paragraphs.forEach((paragraph, i) => {
    const p = drawn[i] ?? article.appendChild(element("p"));
    const runs = speech(paragraph.trim());
    // Two shapes of the same accent: a paragraph that is nothing but
    // speech takes it whole, and a mixed one takes it a run at a time.
    const spoken = runs.length === 1 && runs[0].spoken;
    p.className = spoken ? "otk-prose otk-prose--dialogue" : "otk-prose";
    p.replaceChildren(
      ...runs.map((run) =>
        run.spoken && !spoken
          ? element("span", "otk-quote", run.text)
          : document.createTextNode(run.text),
      ),
    );
  });
  // The cursor rides the end of the text while it is still arriving —
  // the one thing on the page that says the model is still talking.
  $(".otk-caret", article)?.remove();
  if (streaming && article.lastElementChild) {
    const caret = element("span", "otk-caret");
    caret.setAttribute("aria-hidden", "true");
    article.lastElementChild.append(caret);
  }
}

function showTurnBar() {
  /* undo and regenerate belong to the last exchange and to no other —
     the terminal offers them for the same one turn. They live under the
     PROMPT, not under the turn: they are what you do next, and next is
     where the cursor is. Drawn once in the markup, so this only decides
     whether there is anything to act on. */
  const bar = $(".otk-turnbar");
  if (!bar) return;
  const turns = $$(".otk-turn").length;
  bar.hidden = false;
  /* Both act on the last exchange, so both are off when there is no
     exchange to act on. Regenerate answers mid-reply as well — it means
     "not this one" and takes the same door Stop does; undo cannot,
     because the turn it would take back has not landed yet. */
  const undo = $("[data-turn='undo']", bar);
  const regen = $("[data-turn='regen']", bar);
  if (undo) undo.disabled = !turns || playing;
  if (regen) regen.disabled = !turns;
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
  // The bar belongs to the last exchange; from here until this reply
  // lands there is no last exchange, so it has nothing to act on. It is
  // hidden, never removed: it lives in the composer's own row now.
  showTurnBar();
  const article = element("article", "otk-turn is-streaming");
  /* The transcript is a polite live region, and a reply rewrites its
     text several times a second: without this a screen reader is asked
     to re-announce a growing paragraph forty times and says nothing
     useful. `aria-busy` is the standard answer — hold the subtree, and
     announce it once when it settles. */
  article.setAttribute("aria-busy", "true");
  /* Waiting on the model is a state of its own, and on a local model it
     is the long one: the request is away and nothing has come back. The
     terminal spins through it; the page marks it where the reply is
     about to appear, and the mark goes at the first sign of one.
     `aria-busy` above is what says it to a screen reader, so the mark
     itself is decoration. */
  const waiting = element("p", "otk-status");
  waiting.append(element("span", "otk-spinner"));
  waiting.setAttribute("aria-hidden", "true");
  article.classList.add("is-waiting");
  article.append(waiting);
  /* A regenerate takes the standing reply off the screen NOW, before the
     request is even away: the reader asked for another take, and the one
     they are replacing must not sit there while the model thinks. The
     backend validates a regenerate eagerly, so a refusal comes back
     before any of it is lost — and `showTurns` puts the story back as
     the store has it. */
  if (regenerate) holdSpace(dropLastReply);
  showTurnBar();
  return { article, waiting, over, tail, thinking: null, prose: "" };
}

function draw(turn, happened) {
  // A regenerate sends no Recorded — its prompt is already on screen —
  // so the reply's own block joins the flow at the first sign of it, or
  // it would stream into nothing.
  if (!turn.article.isConnected) transcript.append(turn.article);
  // The terminal's own order: any signal clears the wait, and a
  // recorded turn puts it back — that one only says the story took the
  // line, and the reply is still to come.
  turn.waiting.remove();
  turn.article.classList.remove("is-waiting");
  DRAW[happened.type]?.(turn, happened);
  // What arrives goes into the space the old take was read in.
  reserve();
  follow(turn);
}

// One drawer per event kind — `web.api.event`'s closed union, drawn.
const DRAW = {
  recorded(turn, happened) {
    transcript.insertBefore(drawTurn(happened.turn), turn.article);
    turn.article.classList.add("is-waiting");
    turn.article.append(turn.waiting);
  },
  thinking(turn, happened) {
    if (!turn.thinking) {
      turn.thinking = element("p", "otk-thinking", "(thinking) ");
      turn.article.prepend(turn.thinking);
    }
    turn.thinking.textContent += happened.text;
  },
  text(turn, happened) {
    turn.prose += happened.text;
    drawProse(turn.article, turn.prose, { streaming: true });
  },
  declined(turn, happened) {
    turn.article.append(element("p", "otk-error", happened.reason));
  },
  failed(turn, happened) {
    turn.article.append(element("p", "otk-error", `[ error: ${happened.reason} ]`));
  },
  done(turn, happened) {
    if (happened.stats) turn.article.append(element("p", "otk-report", happened.stats));
  },
};

function endTurn(turn) {
  // Whatever ended it — the last event, the reader's Stop, or a
  // connection that went away mid-reply — the turn stops looking like
  // it is still arriving.
  playing = false;
  arriving = null;
  turn.over();
  turnOver(false);
  // Whatever the page had to say about the last attempt is over with
  // the turn it was about.
  tell("");
  turn.waiting.remove();
  turn.article.classList.remove("is-waiting", "is-streaming");
  turn.article.setAttribute("aria-busy", "false");
  $(".otk-caret", turn.article)?.remove();
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
  const last = [...$$(".otk-turn")].pop();
  if (last && !last.classList.contains("otk-turn--user")) last.remove();
}
