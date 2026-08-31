/* The demo's whole server, in the page: `window.fetch` is patched for
   `/api/*` before app.js runs (module scripts execute in document
   order, and the patch is installed synchronously at the top of this
   one), and `EventSource` is replaced for the watch stream. Everything
   else — the page, its scripts, the fixtures — passes through to the
   static host untouched.

   The router mirrors `otaku/web/server.py` route for route and the
   payloads mirror `otaku/web/api.yaml`; `tests/test_architecture.py`
   holds the spec's path list against this file, so an endpoint the demo
   forgot fails the suite. Nothing a visitor does leaves the tab. */

import * as script from "./script.js";
import * as store from "./store.js";

const realFetch = window.fetch.bind(window);

// ---------- fixtures ----------

let version = "";

const ready = (async () => {
  const load = async (name) =>
    (await realFetch(new URL(`./fixtures/${name}.json`, import.meta.url))).json();
  const [syntax, settings, river, tour] = await Promise.all([
    load("syntax"),
    load("settings"),
    load("river"),
    load("tour"),
  ]);
  version = river.facts.version;
  store.seed({ syntax, settings, river, tour });
})();

// ---------- the routes ----------

/* One row per row of `web.api.ROUTES`, keyed the same way: the METHOD
   and a path template, `{name}` standing for one segment. The product's
   server matches these the same way — longest pattern first, so a
   literal segment is never eaten by a parameter. */
const ROUTES = {
  // Playing
  "GET /api/play": () => ({ messages: store.turns() }),
  "GET /api/play/syntax": () => store.syntax(),
  "DELETE /api/play/last": () => store.undo(),
  "GET /api/history": () => ({ lines: store.history() }),
  "POST /api/history": (p, q, b) => store.recordHistory(String(b.line ?? "")),
  // All stories
  "GET /api/stories": (p, q) => ({ stories: store.stories(q.get("q") ?? "") }),
  "POST /api/stories": (p, q, b) =>
    made(
      b.import
        ? importDocument(String(b.import.text ?? ""), String(b.import.name ?? ""))
        : store.newStory(String(b.title ?? "")),
    ),
  "GET /api/stories/{story}": (p) => store.story(num(p.story)),
  "DELETE /api/stories/{story}": (p) => store.deleteStory(num(p.story)),
  "PUT /api/stories/{story}/title": (p, q, b) => store.renameStory(num(p.story), String(b.title)),
  "POST /api/stories/{story}/fork": (p, q, b) =>
    made(
      b.message == null
        ? store.forkStory(num(p.story), String(b.title ?? ""))
        : store.land(num(p.story), num(b.message), "fork"),
    ),
  "PATCH /api/stories/{story}/messages/{message}": (p, q, b) =>
    store.editMessage(num(p.message), String(b.text)),
  "GET /api/stories/{story}/export": (p) => store.exportDocument(num(p.story)),
  // Inside a story
  "PUT /api/stories/{story}/premise": (p, q, b) => store.setSystem(num(p.story), String(b.text)),
  "PATCH /api/stories/{story}/scenes/{scene}": (p, q, b) =>
    store.editLore(
      num(p.story),
      b.title != null ? "scene-title" : "scene-summary",
      num(p.scene),
      String(b.title ?? b.summary),
    ),
  "PATCH /api/stories/{story}/characters/{character}": (p, q, b) =>
    store.editLore(
      num(p.story),
      b.card != null ? "card" : "description",
      num(p.character),
      String(b.card ?? b.description),
    ),
  "PUT /api/stories/{story}/characters/{character}/merge": () => ({
    notice: `Merging characters is not in the demo — ${store.INSTALL}.`,
    refused: true,
  }),
  // The entry is the one writable field — a state is the extractor's
  // own, and the product answers a body without an entry with this
  // sentence (copied: the demo cannot ask it).
  "PATCH /api/stories/{story}/journals/{record}": (p, q, b) =>
    b.entry == null
      ? { notice: "Nothing to change — send one of entry.", refused: true }
      : store.editLore(num(p.story), "entry", num(p.record), String(b.entry)),
  // Extraction
  "GET /api/stories/{story}/extraction": () => ({ report: extraction ? extraction.report : null }),
  "POST /api/stories/{story}/extraction": () => startExtract(),
  "DELETE /api/stories/{story}/extraction": () => stopExtract(),
  // Cards
  "POST /api/cards": () => ({ notice: `Card import is not in the demo — ${store.INSTALL}.`, refused: true }),
  "PUT /api/cards/{token}": () => ({ notice: "No card is waiting.", refused: true }),
  // Models
  "GET /api/providers": (p, q) => store.providers(q.get("scope") ?? ""),
  "GET /api/providers/{provider}": (p) => store.providers(p.provider),
  "PATCH /api/providers/{provider}": () => ({
    notice: `Provider settings are not saved in the demo — ${store.INSTALL}.`,
  }),
  "PATCH /api/providers/{provider}/models/{model}": (p, q, b) =>
    store.loadModel(p.model, Boolean(b.loaded)),
  "PUT /api/session/model": (p, q, b) => store.switchModel(String(b.provider), String(b.model)),
  "PUT /api/session/model/parameters/{name}": (p, q, b) => store.setParameter(p.name, b.value),
  "DELETE /api/session/model/parameters/{name}": (p) => store.setParameter(p.name, "reset"),
  "GET /api/machine": () => store.memory(),
  // The session
  "GET /api/session": () => store.facts(version),
  "PUT /api/session/head": (p, q, b) =>
    store.land(num(b.story), num(b.message), b.discard ? "truncate" : "resume"),
  "GET /api/session/context": () => store.context(),
  "GET /api/session/info": () => store.info(version),
  "GET /api/balance": () => store.balance(),
  "GET /api/usage": (p, q) => store.usage(q.get("scope") ?? ""),
  // Settings
  "GET /api/settings": () => store.settings(),
  "PUT /api/settings/{setting}": (p, q, b) => store.setKnob(p.setting, b.value),
};

// The path parameters that are row ids, as `web/server.py` declares
// them. Every other parameter is a name and may be anything.
const _NUMERIC = ["story", "message", "scene", "character", "record"];

/* The templates, compiled once — longest first, exactly as the server
   sorts them, so `/api/session/model` never matches as a `{setting}`. */
const MATCHERS = Object.entries(ROUTES)
  .map(([key, call]) => {
    const [method, template] = key.split(" ");
    // Row ids match DIGITS, as the product's router matches them: a
    // page that lost its story addresses `/api/stories/null/…`, and the
    // demo must 404 it exactly where otaku does.
    const pattern = new RegExp(
      `^${template.replace(/\{(\w+)}/g, (_, name) =>
        `(?<${name}>${_NUMERIC.includes(name) ? "\\d+" : "[^/]+"})`,
      )}$`,
    );
    return { method, pattern, call };
  })
  .sort((a, b) => b.pattern.source.length - a.pattern.source.length);

function routed(method, path, query, body) {
  for (const route of MATCHERS) {
    if (route.method !== method) continue;
    const found = route.pattern.exec(path);
    if (found) return route.call(found.groups ?? {}, query, body);
  }
  return null;
}

// ---------- the flows that span requests ----------

let extraction = null; // {report: string|null} while a pass runs or waits to be read

function startExtract() {
  if (extraction && extraction.report === null) {
    return { notice: "A pass is already running.", watching: true };
  }
  extraction = { report: null };
  store.setStatus("closing a scene…");
  const run = extraction;
  setTimeout(() => {
    run.report = script.extract().report;
    store.setStatus("");
  }, 2500);
  return { notice: "Extracting lore from the recent messages…", watching: true };
}

function stopExtract() {
  // The page's door to what Ctrl+C does in the terminal: nothing
  // half-done commits, and nothing running refuses like every decline.
  if (!extraction || extraction.report !== null) return { notice: "No pass is running.", refused: true };
  extraction.report = "Cancelled — nothing half-done commits; already-closed scenes stay.";
  store.setStatus("");
  return { notice: extraction.report };
}

function importDocument(text, name) {
  if (!name.toLowerCase().endsWith(".txt")) {
    return {
      notice: `Only plain-text imports work in the demo — ${store.INSTALL} (SillyTavern chats and otaku exports included).`,
      refused: true,
    };
  }
  const paragraphs = text
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean);
  if (!paragraphs.length) {
    return { notice: "The file contains no text to import.", refused: true };
  }
  const landed = store.importStory(paragraphs);
  const started = startExtract();
  return {
    notice: `Imported ${landed.count} message(s) → story ${landed.id}.`,
    // Which story to poll the pass on, so the page need not ask again.
    story: landed.id,
    watching: started.watching,
  };
}

// ---------- the reply stream ----------

function play(body, regenerate, signal) {
  if (regenerate && !store.hasTurns()) {
    return json({ notice: "Nothing to regenerate.", refused: true });
  }
  const line = String(body.line ?? "");
  const events = [];
  if (regenerate) {
    store.dropLastReply();
  } else {
    // `note` is the record's own dim line (a /roll's dice in the real
    // backend); the demo rolls nothing, so it is always empty — but the
    // field arrives, because the shape must not depend on the turn.
    events.push({ type: "recorded", turn: store.recordTurn("user", line), note: "" });
  }
  const reply = script.reply(regenerate);
  const promptTokens = store.contextTokens();
  const started = Date.now();
  let streamed = "";
  let timer = null;

  const land = () => {
    // Whatever ended the stream — the last chunk or a closed reader —
    // what arrived is recorded, exactly as the backend keeps a partial.
    if (!streamed) return;
    store.recordTurn("assistant", streamed);
    store.recordUsage(promptTokens, Math.ceil(streamed.length / 4), (Date.now() - started) / 1000);
    streamed = "";
  };

  const encoder = new TextEncoder();
  const frame = (controller, event) =>
    controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
  let over = false;
  const stream = new ReadableStream({
    start(controller) {
      /* Stop is the reader taking the socket away, and the backend reads
         that as cancel-and-keep: what arrived is recorded, the rest is
         never asked for. `fetch` carries it as an abort signal, which
         the fake has to honour itself — otherwise Stop waits out the
         whole reply and `/regen` mid-reply blocks behind it. */
      const abandon = () => {
        if (over) return;
        over = true;
        clearTimeout(timer);
        land();
        controller.error(new DOMException("Aborted", "AbortError"));
      };
      if (signal) {
        if (signal.aborted) return abandon();
        signal.addEventListener("abort", abandon, { once: true });
      }
      for (const event of events) frame(controller, event);
      const words = reply.split(/(?<=\s)/);
      let at = 0;
      const tick = () => {
        if (at >= words.length) {
          const seconds = (Date.now() - started) / 1000;
          const tokens = Math.ceil(streamed.length / 4);
          const rate = seconds > 0 ? (tokens / seconds).toFixed(1) : "0.0";
          const stats = store.verbose()
            ? `[ total ${seconds.toFixed(1)}s, prompt ${promptTokens} tok, eval ${tokens} tok @ ${rate} tok/s ]`
            : "";
          land();
          frame(controller, { type: "done", stats });
          over = true;
          controller.close();
          return;
        }
        const chunk = words.slice(at, at + 3).join("");
        at += 3;
        streamed += chunk;
        frame(controller, { type: "text", text: chunk });
        timer = setTimeout(tick, 24);
      };
      timer = setTimeout(tick, regenerate ? 350 : 650); // the wait before the first token
    },
    cancel() {
      over = true;
      clearTimeout(timer);
      land();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-store" },
  });
}

// ---------- the patch ----------

window.fetch = async (input, init) => {
  const url = typeof input === "string" ? input : input.url;
  const path = url.split("?")[0];
  if (!path.startsWith("/api/")) return realFetch(input, init);
  await ready;
  const query = new URLSearchParams(url.split("?")[1] ?? "");
  if (path === "/api/alive") return json({ status: store.status(), notices: [] });
  const method = (init && init.method) || "GET";
  const body = init && init.body ? JSON.parse(init.body) : {};
  // The two that answer with a STREAM rather than a payload.
  if (method === "POST" && path === "/api/play") return play(body, false, init && init.signal);
  if (method === "POST" && path === "/api/play/last") return play(body, true, init && init.signal);
  const payload = routed(method, path, query, body);
  if (payload === null) return status(404);
  return payload instanceof Response ? payload : json(payload);
};

// The watch stream ("/api/watch") never has news in the demo: the
// deployed files change only with a deploy, and a deploy serves a new
// page anyway. The fake opens once and stays silently open, so the
// page's restart logic never fires; a stream to any other address is
// nothing the page makes.
window.EventSource = class {
  constructor(url) {
    console.assert(url === "/api/watch", "the page opened an unexpected stream:", url);
    this.listeners = {};
    setTimeout(() => (this.listeners.open || []).forEach((fn) => fn({})), 0);
  }
  addEventListener(type, fn) {
    (this.listeners[type] = this.listeners[type] || []).push(fn);
  }
  close() {}
};

/* A story that was MADE answers 201 and says where it now lives, as the
   product's server does with a `Created`. A refusal stays 200: the
   sentence is the whole answer and nothing was made. */
function made(answer) {
  if (answer.refused) return answer;
  return json(answer, 201, { Location: `/api/stories/${store.openId()}` });
}

function json(payload, code = 200, headers = {}) {
  return new Response(JSON.stringify(payload), {
    status: code,
    headers: { "Content-Type": "application/json; charset=utf-8", ...headers },
  });
}

function status(code) {
  return new Response(null, { status: code });
}

function num(value) {
  return Number(value);
}

// ---------- the demo's own chrome ----------

// The one thing the demo adds to the page: the ribbon that says what
// this is and where the real one lives. Styled by the demo's own
// custom.css — the reader-stylesheet contract, dogfooded.
const ribbon = document.createElement("a");
ribbon.className = "demo-ribbon";
ribbon.href = "https://otaku.sh";
ribbon.target = "_blank";
ribbon.rel = "noopener";
ribbon.textContent = "demo";
document.addEventListener("DOMContentLoaded", () => document.body.append(ribbon));
