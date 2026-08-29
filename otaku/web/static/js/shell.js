/* The frame around the transcript: what the runhead and the rail say
   about the session, whether otaku is there at all, and the one door
   every write comes back through.

   `landed` exists because the rule it carries has been broken three
   times: a redraw REPLACES the flow, so a sentence said before it is
   swept away by its own result. Say it after, once, here — no call site
   has to remember. */

import * as api from "./api.js";
import { guard } from "./browser.js";
import { $, $$ } from "./dom.js";
import { label } from "./format.js";
import { offline, reached, tell, told, working } from "./status.js";
import { isPlaying, showTurns } from "./transcript.js";

const app = $(".otk-app");
const icon = $('link[rel="icon"]');
// The tab icon has no stylesheet to dim it, so the markup carries its
// own greyed copy in `data-offline`. The live one is read once, before
// anything has had a chance to swap it.
const live = icon?.href ?? "";

// The story the transcript is drawing, so a write knows whether the
// ground moved under it.
let drawn = null;

// What the offline line says — needed in two places, so it is named once.
const GONE = "otaku is not answering. The server was stopped in the terminal.";

export function showFacts(facts) {
  const engine = [facts.engine, facts.context && `${facts.context} context`]
    .filter(Boolean)
    .join(" · ");
  const fields = {
    version: `v${facts.version}`,
    model: facts.model,
    engine: engine,
    story: label(facts.story) || "No story yet",
    turns: facts.turns ? `${facts.turns} messages` : "",
  };
  for (const [name, text] of Object.entries(fields)) {
    for (const slot of $$(`[data-fact="${name}"]`)) slot.textContent = text;
  }
  // The rail cuts a long model name to one line, so the whole of it has
  // to be somewhere: hovering the name is where.
  const named = $('[data-fact="model"]');
  if (named) named.title = fields.model;
  drawn = facts.story_id;
}

/** The session again, and the transcript with it. */
export async function refresh() {
  showFacts(await api.facts());
  showTurns(await api.turns());
}

/** What a write answered with, shown where it belongs. The facts are
    always asked again; the transcript is redrawn only when the story it
    draws is no longer the one that is open, because a redraw costs the
    reader their place. */
export async function landed(notice, { redraw = "if-moved", keepPlace = false } = {}) {
  const facts = await api.facts();
  const moved = facts.story_id !== drawn;
  showFacts(facts);
  if (redraw === "always" || (redraw === "if-moved" && moved)) {
    // `keepPlace` is for a write that TAKES something away — an undo:
    // what is above it must not move, and the space it emptied stays
    // empty until something is played into it.
    showTurns(await api.turns(), { keepPlace });
  }
  tell(notice);
}

/* How often the page asks whether otaku is still there. Without it the
   answer only arrives when the reader next asks for something — and the
   place a stopped otaku is most likely to be noticed is a tab in the
   background, which asks for nothing at all. A browser throttles this to
   about a minute once the tab is hidden, which is exactly right: the
   mark is worth a minute of lateness and not a request a second. */
const HEARTBEAT = 5000;

/** Both directions: the page finds out that otaku stopped, and finds
    out that it is back — the same beat answers for both. It also
    carries the background worker's voice: a pass that starts on its own
    after five idle minutes says so here, exactly as it says so in the
    terminal's status row, and the sentence it ends with lands where
    every other sentence otaku says lands.

    `boot` is what a RETURN runs. Coming back is not the same as being
    there: an otaku that answers again has been restarted, and what it
    is open on is its own business — a different story, a different
    model — so the page asks for everything again rather than lifting
    the mark off a transcript that may no longer be the session's. */
export function watchServer(boot) {
  // One answered request is proof otaku is back and one refused
  // connection is proof it is gone — whichever happens, the page says
  // so once, here, rather than at every call site.
  let reachable = true;
  api.whenReached(() => {
    const returned = !reachable;
    reachable = true;
    disconnected(false);
    if (returned) boot();
  });
  api.whenLost(() => {
    reachable = false;
    disconnected();
  });
  let beating = ""; // the worker's line, while the page is showing it
  setInterval(async () => {
    try {
      const beat = await api.alive();
      const sentence = beat.notices?.at(-1);
      if (sentence) {
        tell(sentence);
        beating = "";
      } else if (beat.status) {
        tell(beat.status);
        beating = beat.status;
      } else if (beating && told() === beating) {
        // The pass is over. Its line goes with it — unless the reader
        // has been told something else since, which stays.
        tell("");
        beating = "";
      }
      /* The lamp says what is RUNNING, whoever started it: a pass the
         page forced, one the idle deadline started on its own, and the
         reply, which lights it itself. This beat speaks for the WORKER
         alone, so it must never put out a lamp it did not light — a
         reply is minutes long and the beat is seconds. */
      if (!watcher && !isPlaying()) working(Boolean(beat.status));
    } catch {
      // A beat that cannot be made is the disconnection above, said once.
    }
  }, HEARTBEAT);
}

/* How long the page waits for a forced pass to report, in seconds. A
   long extraction is minutes of model time, so this is generous. */
const EXTRACTION_PATIENCE = 600;
const GAVE_UP = "The pass stopped without a report — see the system log.";

let watcher = null;

/** Watch a forced extraction pass and say what it reports. A pass is one
    line at the END, not a running account, so this polls rather than
    holding a stream open; a delayed answer to a write is `landed`'s
    family, which is why it lives here. One watcher at a time, whatever
    asked for it — two would announce the same pass twice — and bounded,
    or a server stopped mid-pass would leave a timer running for the life
    of the tab.

    A pass the PAGE forced is the one it can also give up on, so the
    status line carries `stop` for as long as this runs. `story` is the
    story it was forced on: a pass belongs to one, and so does the poll
    that asks how it went. */
export function watchExtraction(story) {
  if (watcher) return;
  let left = EXTRACTION_PATIENCE;
  const done = (sentence) => {
    clearInterval(watcher);
    watcher = null;
    working(false);
    tell(sentence);
  };
  // Guarded like every other floating promise the page starts: a Stop
  // that cannot be delivered must say so, not fail into the console.
  const stop = guard(async () => {
    const { notice } = await api.stopExtract(story);
    done(notice);
  });
  working(true, stop);
  watcher = setInterval(async () => {
    /* The lamp is shared with the reply, and a reply that lands clears
       it — so a pass still running takes it back here, once the turn it
       yielded to is over. Re-asserted every tick rather than restored
       once, because there is no moment this could be told about. */
    if (!isPlaying()) working(true, stop);
    let report = null;
    try {
      ({ report } = await api.extractionReport(story));
    } catch {
      // A failed poll is a tick like any other: the server may be busy,
      // and the bound below is what stops this running forever.
    }
    if (report) done(report);
    else if ((left -= 1) <= 0) done(GAVE_UP);
  }, 1000);
}

/** The one failure the page has a state for: otaku stopped answering.
    Said three ways, all of them the page's own: the status line at the
    foot of the contents, the mark in the spine greyed, the tab icon with
    it — a tab in the background is where a stopped server is most likely
    to be noticed — and every control that would reach the session turned
    off, because a door that opens onto nothing should not look like a
    door. Nothing is offered to press: the heartbeat is already asking,
    and the page picks the session up the moment it answers. The TITLE
    never changes: it names the app, not its state. */
export function disconnected(gone = true) {
  app?.classList.toggle("is-offline", gone);
  if (icon) icon.href = (gone && icon.dataset.offline) || live;
  if (gone) {
    tell(GONE, "otk-error");
    offline(true);
  } else {
    // The sentence goes with the state it was about; anything said since
    // is the reader's news and stays.
    if (told() === GONE) tell("");
    reached();
    offline(false);
  }
  for (const control of $$(".otk-toc button, .otk-rail__foot, .otk-composer textarea, [data-send]")) {
    control.disabled = gone;
  }
}
