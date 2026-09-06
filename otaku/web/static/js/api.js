/* Everything the page asks of otaku, one function per endpoint.

   Two shapes cross this line and no others: a JSON value, and the reply
   stream. A refusal is NOT an error here — the backend answers one with
   a sentence, and the caller shows it — so only a broken connection or a
   bug throws.

   The METHOD is the lane. A `get` only reads the session, so the server
   answers it in the gaps of a streaming reply and a screen opens while
   the model talks; everything else moves the story and waits its turn.
   That is the whole reason a read is never written as a POST here. */

/* Every answer is proof that otaku is there, and every connection that
   cannot be made is proof it is not, so the page's connected state is
   settled HERE on every request rather than at each call site. A 404 or
   a 500 is not a loss: the server answered, and answered badly, which
   is a bug to show and not a state to draw. */
let onReach = () => {};
let onLost = () => {};

export function whenReached(callback) {
  onReach = callback;
}

export function whenLost(callback) {
  onLost = callback;
}

async function ask(path, options) {
  let response;
  try {
    response = await fetch(path, options);
  } catch (e) {
    // A reader's own Stop ABORTS the fetch: giving up on a reply is
    // not losing the server, and must not draw the page offline.
    if (e?.name !== "AbortError") onLost();
    throw e;
  }
  onReach();
  if (!response.ok) {
    /* A fault, not a refusal — a refusal comes back 200 with the
       backend's own sentence. There is none for this, so the page says
       the only thing it is entitled to: something about the MEDIUM. The
       address and the code go to the console, where a bug is read. */
    console.error(`${path} — ${response.status}`, await response.text());
    const error = new Error("otaku could not answer that.");
    // Answered, however badly: the caller may show this sentence, and
    // must not draw the offline state for a server that spoke.
    error.answered = true;
    throw error;
  }
  return response;
}

const get = async (path) => (await ask(path)).json();

async function send(method, path, body) {
  const response = await ask(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  return response.json();
}

const post = (path, body) => send("POST", path, body);
const put = (path, body) => send("PUT", path, body);
const patch = (path, body) => send("PATCH", path, body);
const remove = (path, body) => send("DELETE", path, body);

const query = (pairs) => {
  const asked = new URLSearchParams(Object.entries(pairs).filter(([, v]) => v));
  return asked.toString() ? `?${asked}` : "";
};

// ---------- the server, not the session ----------

/** The beat: is otaku there, what is the background worker doing, and
    what has it said since the last one. Answered by the server itself,
    so it is true mid-reply as much as idle — and it is the only request
    the page makes that nobody asked for. */
export const alive = () => get("/api/alive");

// ---------- playing ----------

export const turns = () => get("/api/play").then((it) => it.messages);
export const syntax = () => get("/api/play/syntax");
export const cast = () => get("/api/cast");
export const undo = () => remove("/api/play/last");

export const history = () => get("/api/history").then((it) => it.lines);
export const recordHistory = (line) => post("/api/history", { line });

// ---------- stories ----------

export const stories = (q = "") => get(`/api/stories${query({ q })}`).then((it) => it.stories);
export const story = (id) => get(`/api/stories/${id}`);
export const newStory = (title = "") => post("/api/stories", { title });
export const importStory = (name, text) => post("/api/stories", { import: { name, text } });
export const deleteStory = (id) => remove(`/api/stories/${id}`);
export const setTitle = (id, title) => put(`/api/stories/${id}/title`, { title });
/** Fork a story: from `message` on, or from its head when none is
    given. Answers 201 — the copy is a story that did not exist. */
export const fork = (id, message = null) =>
  post(`/api/stories/${id}/fork`, message == null ? {} : { message });
export const exportDocument = (id) => get(`/api/stories/${id}/export`);

// ---------- inside a story ----------

export const setPremise = (id, text) => put(`/api/stories/${id}/premise`, { text });
export const editMessage = (story, message, text) =>
  patch(`/api/stories/${story}/messages/${message}`, { text });
export const editScene = (story, scene, fields) =>
  patch(`/api/stories/${story}/scenes/${scene}`, fields);
export const editCharacter = (story, character, fields) =>
  patch(`/api/stories/${story}/characters/${character}`, fields);
export const editJournal = (story, record, fields) =>
  patch(`/api/stories/${story}/journals/${record}`, fields);
export const mergeCharacter = (story, character, into) =>
  put(`/api/stories/${story}/characters/${character}/merge`, { into });

// ---------- extraction ----------

export const extractionReport = (story) => get(`/api/stories/${story}/extraction`);
export const extract = (story) => post(`/api/stories/${story}/extraction`);
export const stopExtract = (story) => remove(`/api/stories/${story}/extraction`);

// ---------- cards ----------

export const prepareCard = (name, data, rename = "") =>
  post("/api/cards", { name, data, rename });
export const addCard = (token, persona) => put(`/api/cards/${token}`, { persona });

// ---------- models ----------

/** `scope`: "" the whole set, "local"/"cloud" the terminal's own two
    phases. One provider alone — which is what a Test connection is — is
    its own address, below. */
export const providers = (scope = "") => get(`/api/providers${query({ scope })}`);
export const provider = (name) => get(`/api/providers/${encodeURIComponent(name)}`);
export const saveProviderField = (name, field, value) =>
  patch(`/api/providers/${encodeURIComponent(name)}`, { [field]: value });
export const setLoaded = (provider, model, loaded) =>
  patch(
    `/api/providers/${encodeURIComponent(provider)}/models/${encodeURIComponent(model)}`,
    { loaded },
  );
export const switchModel = (provider, model) => put("/api/session/model", { provider, model });
export const machine = () => get("/api/machine");

// ---------- the session ----------

export const facts = () => get("/api/session");
/** Resume a story at a message, or as it is when `message` is null — a
    story with nothing played has none, and a resume never needed one.
    `discard` sets the later turns aside; without it they stay in the
    database above the tail. */
export const setHead = (story, message, discard = false) =>
  put("/api/session/head", { story, message, discard });
export const context = () => get("/api/session/context");
export const info = () => get("/api/session/info");
export const balance = () => get("/api/balance");
// The slip's first paint: the roster costs no network — rows and notes
// with no figures — and one plain `balance` read then fills them.
export const balanceRoster = () => get("/api/balance?probe=none");
export const usage = (scope = "") => get(`/api/usage${query({ scope })}`);

// ---------- settings ----------

export const settings = () => get("/api/settings");
export const setSetting = (name, value) => put(`/api/settings/${name}`, { value });
export const setParameter = (name, value) =>
  put(`/api/session/model/parameters/${encodeURIComponent(name)}`, { value });
export const resetParameter = (name) =>
  remove(`/api/session/model/parameters/${encodeURIComponent(name)}`);

// ---------- the reply stream ----------

/** Play a line, or regenerate the standing reply. Returns either the
    refusal — checked before anything is recorded — or the event stream. */
export async function play(line, { regenerate = false, signal } = {}) {
  /* A POST like any other; what differs is the body, read frame by
     frame below. `signal` is how a reader gives up: aborting takes the
     socket away, which is the backend's cancel-and-keep door. */
  const response = await ask(regenerate ? "/api/play/last" : "/api/play", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(regenerate ? {} : { line }),
    signal,
  });
  if (response.headers.get("Content-Type")?.startsWith("application/json")) {
    return { refused: (await response.json()).notice };
  }
  return { events: events(response) };
}

async function* events(response) {
  /* An SSE stream read off a POST, which EventSource cannot do. Frames
     are separated by a blank line and can split across chunks, so what
     is left over stays in the buffer until the rest of it arrives.

     However this loop is left — the last frame, a throw while drawing,
     a caller that stops asking — the reader is cancelled, and that is
     what takes the socket away. Without it the backend waits on a reply
     nobody is reading. */
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) return;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop();
      for (const frame of frames) {
        const data = frame.split("\n").find((row) => row.startsWith("data: "));
        if (data) yield JSON.parse(data.slice(6));
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
  }
}
