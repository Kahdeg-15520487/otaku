/* Everything the page asks of otaku, one function per endpoint.

   Two shapes cross this line and no others: a JSON value, and the reply
   stream. A refusal is NOT an error here — the backend answers one with
   a sentence, and the caller shows it — so only a broken connection or a
   bug throws. */

/* Every answer is proof that otaku is there, and every connection that
   cannot be made is proof it is not — so whether the page believes it
   is connected is settled HERE, on every request, rather than at each
   call site, where it was raised and never lowered. A 404 or a 500 is
   not a loss: the server answered, and answered badly, which is a bug
   to show and not a state to draw. */
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
    onLost();
    throw e;
  }
  onReach();
  if (!response.ok) throw new Error(`${path} — ${response.status}`);
  return response;
}

async function get(path) {
  return (await ask(path)).json();
}

async function post(path, body) {
  const response = await ask(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return response.json();
}

// ---------- reading ----------

/* Everything here is `/api/read/`, and the prefix is a promise: these
   only read the session, so the server answers them on its read lane —
   while a reply is streaming as well as between replies. A request that
   changes anything belongs under `/api/do/` (see `act` below). */

/** The beat: is otaku there, what is the background worker doing, and
    what has it said since the last one. Answered by the server itself,
    so it is true of a session in the middle of a reply as much as an
    idle one — and it is the ONLY request the page makes that nobody
    asked for. Reaching it at all is the first answer, which `ask` above
    turns into the page's connected state. */
export const alive = () => get("/api/alive");

/* One function per read, named as the read is — the same vocabulary as
   `web.api.READS`, so a screen, this client, and the server's table all
   call one thing one name. (`facts` is the one exception: the read is
   the sketch's `session` tag, and `session()` here would read as the
   object, not the ask.) */
export const facts = () => get("/api/read/session");
export const turns = () => get("/api/read/turns");
export const commands = () => get("/api/read/commands");
export const stories = () => get("/api/read/stories");
export const storyMessages = (id) => get(`/api/read/story?id=${id}`);
export const search = (q) => get(`/api/read/search?q=${encodeURIComponent(q)}`);
export const lore = () => get("/api/read/lore");
export const providers = () => get("/api/read/providers");
export const settings = () => get("/api/read/settings");
export const context = () => get("/api/read/context");
export const usage = (scope) => get(`/api/read/usage?scope=${encodeURIComponent(scope)}`);
export const balance = () => get("/api/read/balance");
export const info = () => get("/api/read/info");
export const exportDocument = () => get("/api/read/export");
export const extractionReport = () => get("/api/read/extract");

// ---------- writing ----------

/** One command line, and the sentence it answers with. */
export const runCommandLine = (line) => post("/api/command", { line });

/** One write a screen performed. `name` is a row of the backend's own
    ACTIONS table. */
export const act = (name, body) => post(`/api/do/${name}`, body);

// ---------- the reply stream ----------

/** Play a line (or regenerate the standing reply). Returns either the
    refusal — checked before anything is recorded — or the event stream. */
export async function play(line, { regenerate = false, signal } = {}) {
  /* The stream is a POST like any other as far as reaching otaku goes;
     what is different is the body, which is read frame by frame below.
     `signal` is how a reader gives up on it: aborting takes the socket
     away, which is the backend's cancel-and-keep door. */
  const response = await ask("/api/play", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ line, regenerate }),
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
     a caller that stops asking — the reader is cancelled, which is what
     takes the socket away. The backend's cancel-and-keep is on the
     other end of that socket: without this it would wait for a reply
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
