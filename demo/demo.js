/* The demo's whole server, in the page: `window.fetch` is patched for
   `/api/*` before app.js runs (module scripts execute in document
   order, and the patch is installed synchronously at the top of this
   one), and `EventSource` is replaced for the watch stream. Everything
   else — the page, its scripts, the fixtures — passes through to the
   static host untouched.

   The router mirrors `otaku/web/server.py` route for route and the
   payloads mirror `docs/web_api.yaml`; `tests/test_architecture.py`
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
  const [commands, settings, river] = await Promise.all([
    load("commands"),
    load("settings"),
    load("river"),
  ]);
  version = river.facts.version;
  store.seed({ commands, settings, river });
})();

// ---------- the routes ----------

// The read lane: name → payload. One row per row of `web.api.READS`,
// plus the extraction poll the server answers itself.
const READS = {
  "/api/read/session": () => store.facts(version),
  "/api/read/turns": () => store.turns(),
  "/api/read/history": () => store.history(),
  "/api/read/commands": () => store.commandsTable(),
  "/api/read/stories": () => store.stories(),
  "/api/read/search": (q) => store.search(q.get("q") ?? ""),
  "/api/read/story": (q) => {
    const id = q.get("id") ?? "";
    if (!/^\d+$/.test(id)) return status(400);
    return store.storyMessages(Number(id));
  },
  "/api/read/lore": () => store.lore(),
  "/api/read/providers": () => store.providers(),
  "/api/read/settings": () => store.settings(),
  "/api/read/context": () => store.context(),
  "/api/read/usage": (q) => store.usage(q.get("scope") ?? ""),
  "/api/read/balance": () => store.balance(),
  "/api/read/info": () => store.info(version),
  "/api/read/export": () => store.exportDocument(),
  "/api/read/extract": () => ({ report: extraction ? extraction.report : null }),
};

// The write lane's actions and flows: one row per row of
// `web.api.ACTIONS` and `web.api.FLOWS`.
const DOES = {
  "/api/do/land": (b) => store.land(num(b.story), num(b.message), b.action || "resume"),
  "/api/do/set-system": (b) => store.setSystem(String(b.text ?? "")),
  "/api/do/rename-story": (b) => store.renameStory(num(b.story), String(b.title ?? "")),
  "/api/do/delete-story": (b) => store.deleteStory(num(b.story)),
  "/api/do/edit-message": (b) => store.editMessage(num(b.message), String(b.text ?? "")),
  "/api/do/edit-lore": (b) => store.editLore(String(b.kind), num(b.target), String(b.text ?? "")),
  "/api/do/switch-model": (b) => store.switchModel(String(b.provider), String(b.model)),
  "/api/do/load-model": (b) => store.loadModel(String(b.model), Boolean(b.loaded)),
  "/api/do/save-field": () => ({
    notice: `Provider settings are not saved in the demo — ${store.INSTALL}.`,
  }),
  "/api/do/record-history": (b) => store.recordHistory(String(b.line ?? "")),
  "/api/do/import": (b) => importDocument(String(b.text ?? ""), String(b.name ?? "")),
  "/api/do/prepare-card": () => ({
    notice: `Card import is not in the demo — ${store.INSTALL}.`,
  }),
  "/api/do/add-card": () => ({ notice: "No card is waiting." }),
  "/api/do/extract": () => startExtract(),
};

// The command lines this frontend answers with a sentence — the demo's
// half of `web.api.ANSWERS`, over the same shared table.
const ANSWERS = {
  "/fork": (raw) => store.forkStory(raw),
  "/new": (raw) => store.newStory(raw),
  "/title": (raw) => store.setTitle(raw),
  "/merge": () => ({ notice: `/merge is not in the demo — ${store.INSTALL}.`, refused: true }),
  "/system": (raw) => store.setSystem(raw),
  "/set think": (raw) => store.setThink(raw),
  "/set parameter": (raw) => store.setParameter(raw),
  "/set verbose": (raw) => store.setToggle("verbose", raw),
  "/set autocorrect": (raw) => store.setToggle("autocorrect", raw),
  "/set notification": (raw) => store.setToggle("notification", raw),
  "/model": (raw) => store.switchSpec(raw),
  "/undo": () => store.undo(),
};

function command(line) {
  // `backend.commands.find` + `raw_argument`, over the fixture's table:
  // longest match first, argument verbatim from the first non-space.
  const words = line.trim().split(/\s+/);
  for (const depth of [2, 1]) {
    const token = words.slice(0, depth).join(" ");
    if (ANSWERS[token]) {
      let rest = line;
      for (let i = 0; i < depth; i++) rest = rest.trimStart().split(" ").slice(1).join(" ");
      return ANSWERS[token](rest.trimStart());
    }
  }
  return store.unknownNotice(line);
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

function importDocument(text, name) {
  if (!name.toLowerCase().endsWith(".txt")) {
    return {
      notice: `Only plain-text imports work in the demo — ${store.INSTALL} (SillyTavern chats and otaku exports included).`,
      watching: false,
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
    watching: started.watching,
  };
}

// ---------- the reply stream ----------

function play(body) {
  const regenerate = Boolean(body.regenerate);
  if (regenerate && !store.hasTurns()) {
    return json({ notice: "Nothing to regenerate.", refused: true });
  }
  const line = String(body.line ?? "");
  const events = [];
  if (regenerate) {
    store.dropLastReply();
  } else {
    events.push({ type: "recorded", turn: store.recordTurn("user", line) });
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
  const stream = new ReadableStream({
    start(controller) {
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
  if (path in READS) {
    const payload = READS[path](query);
    return payload instanceof Response ? payload : json(payload);
  }
  const body = init && init.body ? JSON.parse(init.body) : {};
  if (path === "/api/play") return play(body);
  if (path === "/api/command") return json(command(String(body.line ?? "")));
  if (path in DOES) return json(DOES[path](body));
  return status(404);
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

function json(payload) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json; charset=utf-8" },
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
ribbon.textContent = "demo · scripted model — get otaku";
document.addEventListener("DOMContentLoaded", () => document.body.append(ribbon));
