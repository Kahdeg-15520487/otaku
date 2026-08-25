/* The demo's session: the state a real otaku keeps below both
   frontends, held in this tab's memory instead. Seeded from the
   captured fixtures (the shipped sample story, read off a real
   session), mutated by the same operations the page performs, and
   forgotten on reload — which makes reload the demo's reset button.

   Sentences mirror the backend's wording (`otaku/backend/api/*`)
   so the demo answers exactly as the product would; anything the demo
   deliberately cannot do says so honestly and points at the install. */

// What the fake engine claims to be. One provider with two models, so
// the picker's switch, load and unload have something real to do.
export const PROVIDER = "demo";
const MODELS = [
  { name: "scripted-model", loaded: true, can_load_unload: true, size: "4.7 GB", context: "8K" },
  { name: "scripted-model-mini", loaded: false, can_load_unload: true, size: "1.9 GB", context: "32K" },
];
const WINDOW = 8192;

export const INSTALL = "install otaku from otaku.sh to do this for real";

const state = {
  stories: new Map(), // id → {title, system, turns:[{id,role,body}], updatedAt}
  lore: new Map(), // id → {scenes:[…], cast:[…]} as the lore read shapes them
  open: null, // the open story's id
  nextStory: 1,
  nextMessage: 1,
  model: "scripted-model",
  settings: null, // seeded from the settings fixture; values live here
  history: [], // the composer's ↑/↓ lines, most recent first
  usage: [], // one row per completed reply: {story, prompt, completion, seconds}
  commands: null, // the shared table fixture, for usage lines and menus
  contextFixture: null, // the captured preview, served until the story moves
  contextStory: null, // …for this story only
  status: "", // what /api/alive reports the worker doing
};

export function seed(fixtures) {
  const { river, settings, commands } = fixtures;
  state.commands = commands;
  state.settings = structuredClone(settings);
  const id = state.nextStory++;
  state.stories.set(id, {
    title: river.story.title || "",
    system: river.facts.system || "",
    turns: river.turns.map((t) => ({ ...t })),
    updatedAt: river.story.updated_at,
  });
  state.lore.set(id, structuredClone(river.lore));
  state.open = id;
  state.nextMessage = Math.max(0, ...river.turns.map((t) => t.id)) + 1;
  state.contextFixture = river.context;
  state.contextStory = id;
}

// ---------- reads ----------

export function facts(version) {
  const story = state.stories.get(state.open);
  const model = MODELS.find((m) => m.name === state.model);
  return {
    version,
    model: state.model,
    engine: "scripted",
    context: model ? model.context : "",
    story: story ? label(story) : "",
    story_id: state.open,
    turns: story ? story.turns.length : 0,
    system: story ? story.system : "",
    think: state.settings.think,
    verbose: state.settings.verbose,
    autocorrect: state.settings.autocorrect,
    notification: state.settings.notification,
  };
}

export function turns() {
  const story = state.stories.get(state.open);
  return story ? story.turns.map((t) => ({ ...t })) : [];
}

export function history() {
  return [...state.history];
}

export function commandsTable() {
  return state.commands;
}

export function stories() {
  return [...state.stories.entries()]
    .sort((a, b) => (a[1].updatedAt < b[1].updatedAt ? 1 : -1))
    .map(([id, s]) => ({
      id,
      label: label(s),
      title: s.title,
      story_so_far: storySoFar(id),
      first_user: firstUser(s),
      model: `${PROVIDER}/${state.model}`,
      updated_at: s.updatedAt,
      messages: s.turns.length,
      open: id === state.open,
    }));
}

export function search(q) {
  const needle = q.trim().toLowerCase();
  const ids = [];
  for (const [id, s] of state.stories) {
    const face = `${label(s)} ${storySoFar(id)} ${firstUser(s)} ${PROVIDER}/${state.model}`;
    const chain = s.turns.map((t) => t.body).join(" ");
    if (!needle || `${face} ${chain}`.toLowerCase().includes(needle)) ids.push(id);
  }
  return ids.sort((a, b) => a - b);
}

export function storyMessages(id) {
  const story = state.stories.get(id);
  return story ? story.turns.map((t) => ({ ...t })) : [];
}

export function lore() {
  const memory = state.lore.get(state.open);
  if (!memory) return { notice: "No story yet — send a message first.", refused: true };
  return structuredClone(memory);
}

export function providers() {
  return {
    current: `${PROVIDER}/${state.model}`,
    memory: "RAM: 23.4 / 64.0 GB (37%)",
    engines: [
      {
        name: PROVIDER,
        label: "Demo",
        local: true,
        connected: true,
        url: "in this browser tab",
        has_key: false,
        models: MODELS.map((m) => ({ ...m })),
      },
      ...[
        ["ollama", "Ollama", "http://localhost:11434/v1"],
        ["omlx", "oMLX", "http://localhost:8100/v1"],
        ["koboldcpp", "KoboldCpp", "http://localhost:5001/v1"],
        ["llamacpp", "llama.cpp", "http://localhost:8080/v1"],
        ["lmstudio", "LM Studio", "http://localhost:1234/v1"],
      ].map(([name, labelled, url]) => ({
        name,
        label: labelled,
        local: true,
        connected: false,
        url,
        has_key: false,
        models: [],
      })),
      ...[
        ["openrouter", "OpenRouter", "https://openrouter.ai/api/v1"],
        ["nanogpt", "NanoGPT", "https://nano-gpt.com/api/v1"],
      ].map(([name, labelled, url]) => ({
        name,
        label: labelled,
        local: false,
        connected: false,
        url,
        has_key: false,
        models: [],
      })),
    ],
  };
}

export function settings() {
  const s = state.settings;
  return {
    think: s.think,
    think_levels: s.think_levels,
    verbose: s.verbose,
    autocorrect: s.autocorrect,
    notification: s.notification,
    model: state.model,
    parameters: s.parameters.map((p) => ({ ...p })),
  };
}

export function context() {
  // The captured preview is the real assembler's work and is served as
  // long as it is true; a story that moved gets an honest recompute.
  if (state.open === state.contextStory && state.contextFixture) return state.contextFixture;
  const story = state.stories.get(state.open);
  const bodies = story ? story.turns : [];
  const system = story ? story.system : "";
  const systemTokens = estimate(system);
  const transcript = bodies.reduce((n, t) => n + estimate(t.body), 0);
  const total = systemTokens + transcript;
  const used = Math.round((100 * total) / WINDOW);
  const lede =
    "Context preview — the exact request to be sent. Context summary:\n\n" +
    `  ~${total.toLocaleString("en-US")} tokens · ${used}% of the ${WINDOW.toLocaleString("en-US")} window\n` +
    (systemTokens ? `  system ${systemTokens.toLocaleString("en-US")} · transcript ${transcript.toLocaleString("en-US")}\n` : "") +
    `  ${bodies.length} messages verbatim`;
  return {
    shape: {
      head: 0,
      tail: 0,
      middle: 0,
      kept: bodies.length,
      summaries: 0,
      rolled_up: 0,
      total_tokens: total,
      system_tokens: systemTokens,
      transcript_tokens: transcript,
      context_max: WINDOW,
      used,
    },
    lede,
    parts: [
      ...(system ? [{ role: "system", body: system }] : []),
      ...bodies.map((t) => ({ role: t.role, body: t.body })),
    ],
  };
}

export function usage(scope) {
  const scopes = [
    { key: "", label: "this story" },
    { key: "all", label: "all stories" },
  ];
  if (scope !== "" && scope !== "all") return { notice: "Usage: /usage [all]", scopes };
  const rows = scope === "all" ? state.usage : state.usage.filter((r) => r.story === state.open);
  if (!rows.length) {
    return {
      notice: scope === "all" ? "No recorded usage yet." : "No recorded usage for this story.",
      scopes,
    };
  }
  const prompt = rows.reduce((n, r) => n + r.prompt, 0);
  const completion = rows.reduce((n, r) => n + r.completion, 0);
  const seconds = rows.reduce((n, r) => n + r.seconds, 0);
  return {
    scope: scope === "all" ? "all stories" : "this story",
    scopes,
    rows: [
      {
        purpose: "chat",
        provider: PROVIDER,
        model: state.model,
        requests: rows.length,
        prompt_tokens: prompt,
        completion_tokens: completion,
        cached_tokens: 0, // the scripted model keeps no cache to read from
        rate: seconds > 0 ? completion / seconds : 0,
      },
    ],
    requests: rows.length,
    prompt_tokens: prompt,
    completion_tokens: completion,
    cached_tokens: 0,
    total_tokens: prompt + completion,
  };
}

export function balance() {
  return {
    rows: [
      { provider: "openrouter", label: "OpenRouter", value: "—" },
      { provider: "nanogpt", label: "NanoGPT", value: "—" },
    ],
  };
}

export function info(version) {
  const story = state.stories.get(state.open);
  const session = [["Messages", String(story ? story.turns.length : 0)]];
  if (story) session.unshift(["Story", cut(label(story), 50)]);
  if (story && story.system) session.push(["System", `"${story.system}"`]);
  const set = state.settings.parameters.filter((p) => p.value);
  if (set.length) session.push(["Parameters", set.map((p) => `${p.name} = ${p.value}`).join(", ")]);
  return {
    sections: [
      { rows: [["State dir", "(this browser tab — nothing leaves it)"]], note: "" },
      {
        rows: [
          ["Model", `${PROVIDER}/${state.model}`],
          ["Backend", "scripted (a demo model that lives in the page)"],
          ["Context", modelRow().context],
          ["Thinking", "not supported"],
        ],
        note: "",
      },
      { rows: session, note: `otaku ${version} — this is the scripted demo; ${INSTALL}.` },
    ],
  };
}

export function exportDocument() {
  const story = state.stories.get(state.open);
  if (!story || !story.turns.length) return { notice: "Nothing to export yet.", refused: true };
  const name = `${slug(label(story)) || "story"}.md`;
  const text = [
    `# ${label(story)}`,
    "",
    "*Played in the otaku demo — a real otaku exports the full document, memory included.*",
    "",
    ...story.turns.map((t) => (t.role === "user" ? `> ${t.body}` : t.body)),
  ].join("\n\n");
  return { name, text };
}

// ---------- the writes a screen performs ----------

export function land(storyId, messageId, action) {
  const story = state.stories.get(storyId);
  if (!story) return refuse("That message is not on the story's current chain.");
  const at = story.turns.findIndex((t) => t.id === messageId);
  if (at < 0) return refuse("That message is not on the story's current chain.");
  if (action === "fork") {
    const id = addStory(numberedTitle(story.title), story.system, story.turns.slice(0, at + 1));
    state.open = id;
    const named = cut(label(state.stories.get(id)), 50);
    const lead = named ? `Forked to: ${named}. ` : "Forked. ";
    return say(`${lead}Continued from message ${at + 1}.`);
  }
  if (action === "truncate") {
    story.turns = story.turns.slice(0, at + 1);
    touch(storyId);
    state.open = storyId;
    return say(landed("Truncated"));
  }
  state.open = storyId;
  return say(landed("Resumed"));
}

export function setSystem(text) {
  const story = state.stories.get(state.open);
  if (!text) {
    const current = story && story.system;
    return say(current ? `System: "${current}"` : "System: (none)");
  }
  if (story) {
    story.system = text;
    touch(state.open);
  }
  return say(`System prompt set (${text.length} chars).`);
}

export function renameStory(storyId, title) {
  if (!title.trim()) return refuse("A story needs a title — or leave the one it has.");
  const story = state.stories.get(storyId);
  if (story) {
    story.title = title.trim();
    touch(storyId);
  }
  return say(`Story title set to "${title.trim()}".`);
}

export function deleteStory(storyId) {
  state.stories.delete(storyId);
  state.lore.delete(storyId);
  if (state.open === storyId) state.open = null;
  return say("Story deleted.");
}

export function editMessage(messageId, body) {
  if (!body.trim()) return refuse("A message cannot be emptied — undo the exchange instead.");
  for (const [id, story] of state.stories) {
    const turn = story.turns.find((t) => t.id === messageId);
    if (turn) {
      turn.body = body;
      touch(id);
      moved();
      return say("Message edited.");
    }
  }
  return say("Message edited.");
}

export function editLore(kind, target, text) {
  if (kind === "history") return refuse("The history is derived — correct the entries and it rebuilds.");
  if (kind === "scene-summary" && !text.trim()) {
    return refuse("An emptied summary would swallow its scene — not saved.");
  }
  const memory = state.lore.get(state.open);
  if (!memory) return refuse("No story yet — send a message first.");
  for (const scene of memory.scenes) {
    if (kind === "scene-title" && scene.id === target) scene.title = text;
    if (kind === "scene-summary" && scene.id === target) scene.summary = text;
    for (const field of scene.fields) if (field.kind === kind && field.target === target) field.text = text;
  }
  for (const person of memory.cast) {
    if (kind === "description" && person.id === target) person.description = text;
    for (const field of person.fields) {
      if (field.kind === kind && field.target === target) {
        field.text = text;
        if (field.kind === "state" && person.fields.filter((f) => f.kind === "state").at(-1) === field) {
          person.now = text;
        }
      }
    }
  }
  refreshLoreLabels(memory);
  return say("Saved.");
}

export function switchModel(provider, model) {
  if (provider !== PROVIDER) return refuse(`Unknown provider '${provider}'.`);
  if (model === state.model) return refuse(`Already using ${PROVIDER}/${state.model}.`);
  if (!MODELS.some((m) => m.name === model)) {
    return say(`Switched to ${PROVIDER}/${model}.`); // the real backend trusts the name too
  }
  state.model = model;
  return say(`Switched to ${PROVIDER}/${state.model}.`);
}

export function switchSpec(raw) {
  const [head, ...rest] = raw.trim().split("/");
  const known = providers().engines.map((e) => e.name);
  if (!known.includes(head) || !rest.length || !rest.join("/")) {
    return refuse(
      `Use PROVIDER/MODEL (providers: ${[...known].sort().join(", ")}), or /model with no args to pick.`,
    );
  }
  if (head !== PROVIDER) {
    return refuse(`Only the demo provider answers here — ${INSTALL}.`);
  }
  return switchModel(head, rest.join("/"));
}

export function loadModel(model, wanted) {
  const row = MODELS.find((m) => m.name === model);
  if (!row || !row.can_load_unload) return refuse(`${PROVIDER} cannot load or unload models.`);
  row.loaded = wanted;
  return say(wanted ? `Loaded ${model}.` : `Unloaded ${model}.`);
}

export function recordHistory(line) {
  const said = line.trim();
  if (!said || state.history[0] === said) return say("");
  state.history.unshift(said);
  state.history.length = Math.min(state.history.length, 100);
  return say("");
}

// ---------- the story-level operations (/api/command rows) ----------

export function newStory(title) {
  const id = addStory(title.trim(), "", []);
  state.open = id;
  if (!title.trim()) return say("Started a new story.");
  return say(`Started a new story: "${cut(title.trim(), 50)}".`);
}

export function forkStory(title) {
  const story = state.stories.get(state.open);
  if (!story || !story.turns.length) return refuse("Nothing to fork yet — send a message first.");
  const id = addStory(title.trim() || numberedTitle(story.title), story.system, story.turns);
  state.open = id;
  const named = cut(label(state.stories.get(id)), 50);
  return say(named ? `Forked to: ${named}.` : "Forked.");
}

export function setTitle(raw) {
  const title = raw.trim();
  const story = state.stories.get(state.open);
  if (!title) {
    const current = story && story.title;
    return say(current ? `Title: "${current}"` : "Usage: /title NEW-TITLE");
  }
  if (!story) return say(`Story title set to "${title}".`);
  story.title = title;
  touch(state.open);
  return say(`Story title set to "${title}".`);
}

export function undo() {
  const story = state.stories.get(state.open);
  const popped = [];
  if (story && story.turns.at(-1)?.role === "assistant") popped.push(story.turns.pop());
  if (story && story.turns.at(-1)?.role === "user") popped.push(story.turns.pop());
  if (!popped.length) return refuse("Nothing to undo.");
  touch(state.open);
  moved();
  return say(`Took back the last exchange (${popped.length} messages).`);
}

export function setToggle(name, raw) {
  const value = raw.trim().toLowerCase();
  const labels = { verbose: "Verbose", autocorrect: "Autocorrect", notification: "Notification" };
  if (value) {
    if (["on", "true", "yes"].includes(value)) state.settings[name] = true;
    else if (["off", "false", "no"].includes(value)) state.settings[name] = false;
    else return refuse(`Usage: /set ${name} on|off`);
  }
  return say(`${labels[name]}: ${state.settings[name] ? "on" : "off"}.`);
}

export function setThink(raw) {
  const s = state.settings;
  if (!raw.trim()) return say(`Think: ${s.think}.`);
  const aliases = { on: "medium", off: "none" };
  const value = aliases[raw.trim().toLowerCase()] || raw.trim().toLowerCase();
  if (value === "default") {
    s.think = "default";
    return say("Think: default (nothing sent — the model decides).");
  }
  if (!s.think_levels.includes(value)) {
    return refuse("Usage: /set think on|off|none|low|medium|high|max|default");
  }
  s.think = value;
  return say(`Think: ${value}.`);
}

export function setParameter(raw) {
  const tokens = raw.split(/\s+/).filter(Boolean);
  const params = state.settings.parameters;
  if (!tokens.length) {
    const set = params.filter((p) => p.value);
    if (!set.length) return say("No parameters set.");
    return say(`Parameters:\n${set.map((p) => `  ${p.name} = ${p.value}.`).join("\n")}`);
  }
  const [name, ...restTokens] = tokens;
  const row = params.find((p) => p.name === name);
  if (!row) return refuse(`Unknown parameter '${name}'. Known: ${params.map((p) => p.name).join(", ")}.`);
  const rest = restTokens.join(" ");
  if (!rest) {
    if (row.value) return say(`${name} = ${row.value}`);
    return say(`Parameter ${name} is at the model's own default.`);
  }
  if (rest.toLowerCase() === "reset") {
    if (!row.value) return say(`Parameter ${name} is already at its default.`);
    row.value = "";
    return say(`Parameter ${name} reset to default.`);
  }
  if (row.type === "float" && Number.isNaN(Number.parseFloat(rest))) {
    return refuse(`Could not parse '${rest}' as float.`);
  }
  if (row.type === "int" && !/^-?\d+$/.test(rest)) return refuse(`Could not parse '${rest}' as int.`);
  row.value = rest;
  return say(`${name} = ${rest}.`);
}

export function unknownNotice(line) {
  // `backend.commands.unknown_notice`, mirrored over the fixture's table so
  // the /set usage line is composed from the same rows.
  const word = line.trim().split(" ")[0] || "";
  if (word === "/set") {
    const forms = state.commands.rows
      .filter((r) => r.token.startsWith("/set "))
      .map((r) => `${r.token} ${r.args}`.trim())
      .join(" | ");
    return refuse(`Usage: ${forms}`);
  }
  return refuse(`Unknown command: ${word}. Type /help.`);
}

// ---------- what the reply stream needs ----------

export function recordTurn(role, body) {
  let story = state.stories.get(state.open);
  if (!story) {
    // The first real turn creates the story, exactly as the backend does.
    const id = addStory("", "", []);
    state.open = id;
    story = state.stories.get(id);
  }
  const turn = { id: state.nextMessage++, role, body };
  story.turns.push(turn);
  touch(state.open);
  moved();
  return { ...turn };
}

export function dropLastReply() {
  const story = state.stories.get(state.open);
  if (!story || story.turns.at(-1)?.role !== "assistant") return null;
  const popped = story.turns.pop();
  touch(state.open);
  moved();
  return popped;
}

export function hasTurns() {
  const story = state.stories.get(state.open);
  return Boolean(story && story.turns.length);
}

export function openTurns() {
  const story = state.stories.get(state.open);
  return story ? story.turns : [];
}

export function verbose() {
  return state.settings.verbose;
}

export function recordUsage(prompt, completion, seconds) {
  state.usage.push({ story: state.open, prompt, completion, seconds });
}

export function contextTokens() {
  return context().shape.total_tokens;
}

// ---------- the lore pass ----------

export function memoryOf(storyId) {
  if (!state.lore.has(storyId)) state.lore.set(storyId, { scenes: [], cast: [] });
  return state.lore.get(storyId);
}

export function openId() {
  return state.open;
}

export function setStatus(line) {
  state.status = line;
}

export function status() {
  return state.status;
}

// ---------- internals ----------

function addStory(title, system, turns) {
  const id = state.nextStory++;
  state.stories.set(id, {
    title,
    system,
    turns: turns.map((t) => ({ ...t })),
    updatedAt: new Date().toISOString(),
  });
  return id;
}

export function importStory(paragraphs) {
  const turnsIn = paragraphs.map((body, i) => ({
    id: state.nextMessage++,
    role: i % 2 ? "assistant" : "user",
    body,
  }));
  const id = addStory("", "", []);
  state.stories.get(id).turns = turnsIn;
  state.open = id;
  moved();
  return { id, count: turnsIn.length };
}

function landed(verb) {
  const story = state.stories.get(state.open);
  const named = story ? cut(label(story), 50) : "";
  const head = named ? `Story: ${named}. ` : "";
  return `${head}${verb} at message ${story ? story.turns.length : 0}.`;
}

function numberedTitle(title) {
  return title ? `${title} - 2` : "";
}

function label(story) {
  if (story.title) return flatten(story.title);
  const id = [...state.stories.entries()].find(([, s]) => s === story)?.[0];
  const arc = id ? storySoFar(id) : "";
  if (arc) return flatten(arc);
  return flatten(firstUser(story));
}

function storySoFar(id) {
  const memory = state.lore.get(id);
  const withHistory = memory?.cast.flatMap((c) => c.fields).filter((f) => f.kind === "history") ?? [];
  // The captured lore carries the sample's story-so-far on its scenes'
  // summaries; the listing wants the arc line, which the fixture's
  // story row supplied at seed time — after that, the newest summary
  // stands in.
  const scenes = memory?.scenes ?? [];
  return withHistory.at(-1)?.text || scenes.at(-1)?.summary || "";
}

function firstUser(story) {
  return story.turns.find((t) => t.role === "user")?.body || "";
}

function refreshLoreLabels(memory) {
  for (const scene of memory.scenes) {
    const no = memory.scenes.indexOf(scene) + 1;
    scene.label = [no, scene.span, flatten(scene.title)].filter(Boolean).join("  ");
    for (const field of scene.fields) if (field.kind === "scene-title") field.text = scene.title;
  }
}

function touch(id) {
  const story = state.stories.get(id);
  if (story) story.updatedAt = new Date().toISOString();
}

function moved() {
  // The captured context preview stops being true the moment the story
  // moves; the recompute takes over.
  state.contextStory = null;
}

function modelRow() {
  return MODELS.find((m) => m.name === state.model) ?? MODELS[0];
}

function estimate(text) {
  return Math.ceil(text.length / 4);
}

function flatten(text) {
  return text.replace(/\s+/g, " ").trim();
}

function cut(text, limit) {
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function slug(text) {
  return text
    .toLowerCase()
    .replace(/[^\w\s-]/g, "")
    .replace(/[\s_-]+/g, "-")
    .replace(/^-|-$/g, "");
}

function say(notice) {
  return { notice };
}

function refuse(notice) {
  return { notice, refused: true };
}
