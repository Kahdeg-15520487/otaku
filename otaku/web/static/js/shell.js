/* The frame around the transcript: what the header and the rail say
   about the session, whether otaku is there at all, and the one door
   every write comes back through.

   `landed` exists because the rule it carries has been broken three
   times: a redraw REPLACES the flow, so a sentence said before it is
   swept away by its own result. Say it after, once, here — no call site
   has to remember. */

import * as api from "./api.js";
import { $, $$ } from "./dom.js";
import { showTurns, tell, told } from "./transcript.js";

const banner = $(".otk-banner");
const app = $(".otk-app");
const icon = $('link[rel="icon"]');
// The tab icon has no stylesheet to dim it, so it carries its own greyed
// copy (`scripts/mascot.py` writes both). The live one is read once,
// before anything has had a chance to swap it.
const live = icon?.href ?? "";

// The story the transcript is drawing, so a write knows whether the
// ground moved under it.
let drawn = null;

export function showFacts(facts) {
  const engine = [facts.engine, facts.context && `${facts.context} context`]
    .filter(Boolean)
    .join(" · ");
  const fields = {
    version: `v${facts.version}`,
    model: facts.model,
    engine: engine,
    story: facts.story || "No story yet",
    turns: facts.turns ? `${facts.turns} messages` : "",
  };
  for (const [name, text] of Object.entries(fields)) {
    const slot = $(`[data-fact="${name}"]`);
    if (slot) slot.textContent = text;
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
    of the tab. */
export function watchExtraction() {
  if (watcher) return;
  let left = EXTRACTION_PATIENCE;
  const done = (sentence) => {
    clearInterval(watcher);
    watcher = null;
    tell(sentence);
  };
  watcher = setInterval(async () => {
    let report = null;
    try {
      ({ report } = await api.extractionReport());
    } catch {
      // A failed poll is a tick like any other: the server may be busy,
      // and the bound below is what stops this running forever.
    }
    if (report) done(report);
    else if ((left -= 1) <= 0) done(GAVE_UP);
  }, 1000);
}

/** The one failure the page has a state for: otaku stopped answering.
    Said four ways, all of them the page's own: the banner in the flow,
    the mark in the rail greyed, the tab icon with it — a tab in the
    background is where a stopped server is most likely to be noticed —
    and every control that would reach the session turned off, because a
    door that opens onto nothing should not look like a door. The retry
    button is the one thing still live, and the TITLE never changes: it
    names the app, not its state. */
export function disconnected(gone = true) {
  banner.hidden = !gone;
  app?.classList.toggle("is-offline", gone);
  if (icon) icon.href = (gone && icon.dataset.offline) || live;
  for (const control of $$(".otk-rail button, .otk-composer__input, [data-send]")) {
    control.disabled = gone;
  }
}
