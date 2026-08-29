/* The model picker: every catalog otaku can reach on one tab, and the
   providers behind them on the other — the two halves of the same
   panel, because a model that is missing is fixed on the provider side.

   It opens the way the terminal's picker opens: on the local engines,
   NOW — and each cloud catalog's rows arrive when it answers, merged in
   behind the open panel. Testing a connection is re-asking the same
   read the picker is drawn from, for that one provider: a provider
   that answers the catalog IS the test.

   An api key's VALUE never arrives on this side; only whether one is
   set. */

import * as api from "./api.js";
import { ask, browser, closeAll, footnote, guard, popups, wiring } from "./browser.js";
import { $, $$, actionButton, element, row, span } from "./dom.js";
import { landed } from "./shell.js";

export async function openModels(answered = "", tab = "models") {
  const popup = popups.get("/model");
  // The panel is up before its data: a click must answer NOW, and the
  // modal keeps further clicks from queueing screens behind it.
  if (!popup.open) popup.showModal();

  const state = { popup, panel: await api.providers("local"), tab, picked: null };
  $("[data-memory]", popup).textContent = state.panel.memory || "";
  watchMemory(popup);
  const build = (wanted, notice = "") => {
    state.tab = wanted;
    for (const button of $$(".otk-tab", popup)) {
      button.setAttribute("aria-selected", String(button.dataset.tab === wanted));
    }
    for (const pane of $$("[data-pane]", popup)) {
      pane.hidden = pane.dataset.pane !== wanted;
    }
    if (wanted === "models") buildModels(state, notice);
    else buildProviders(state, notice);
  };
  state.build = build;
  for (const button of $$(".otk-tab", popup)) {
    button.onclick = () => build(button.dataset.tab);
  }
  build(tab, answered);

  // The cloud catalogs answer at their own pace, behind the open
  // panel — merged in and redrawn wherever the reader is by then.
  api.providers("cloud").then(
    guard((cloud) => {
      if (!popup.open) return;
      state.panel = {
        ...state.panel,
        engines: [...state.panel.engines, ...cloud.engines],
      };
      build(state.tab);
    }),
  );
}

// How often the gauge is re-read while the picker is open. Loading a
// model is the one thing that fills a machine up, and it fills while the
// reader watches — so the figure has to move, not stand still until the
// panel is reopened.
const _MEMORY_MS = 1000;

let _gauge = 0;

function watchMemory(popup) {
  /* The gauge, for as long as the panel is up. It is its own read: the
     picker's inventory costs every engine a probe, and this costs a
     syscall. One timer at a time — reopening the panel must not leave
     the last one running — and it dies with the panel, so a closed
     picker asks nothing. */
  clearInterval(_gauge);
  const slot = $("[data-memory]", popup);
  _gauge = setInterval(async () => {
    if (!popup.open) return clearInterval(_gauge);
    /* A gauge is not worth an error. Every other floating promise on
       this page goes through `guard`, which SAYS what failed; this one
       is asked for once a second and nobody asked for it at all, so a
       tick that cannot be answered leaves the last figure standing and
       the next tick tries again. Unguarded, one dead request per second
       becomes one unhandled rejection per second. */
    let memory = "";
    try {
      ({ memory } = await api.machine());
    } catch {
      return;
    }
    // Only while it is still up: a read in flight when the panel closed
    // must not write into a slot the next screen is using.
    if (popup.open) slot.textContent = memory || "";
  }, _MEMORY_MS);
}

// ---------- the models tab ----------

function buildModels(state, notice) {
  const { popup, panel } = state;
  const pane = $('[data-pane="models"]', popup);
  const offered = panel.engines.flatMap((engine) =>
    engine.models.map((model) => ({ engine, model, haystack: model.name.toLowerCase() })),
  );
  const local = offered.filter((entry) => entry.engine.local).length;
  const remote = offered.length - local;
  $("[data-tabs-aside]", popup).textContent =
    `${offered.length} ${offered.length === 1 ? "model" : "models"}`;
  footnote(popup, notice || `${local} on this machine · ${remote} over the wire`);

  const use = async (entry) => {
    const { notice: said } = await api.switchModel(entry.engine.name, entry.model.name);
    closeAll();
    await landed(said, { redraw: "always" });
  };

  const setLoaded = async (entry, wanted) => {
    if (!entry?.model.can_load_unload) return;
    const { notice: said } = await api.setLoaded(entry.engine.name, entry.model.name, wanted);
    /* What changed is one flag on one model — so that is what changes
       here. Asking the catalogs again would cost every provider a round
       trip to redraw a lamp, and would move the list under the reader
       who just aimed at it. */
    entry.model.loaded = wanted;
    state.build("models", said);
  };

  if (!offered.length) $("[data-actions]", pane).replaceChildren();
  /* Read BEFORE the browser paints: its first paint moves the cursor to
     row 0 and `onMove` would overwrite what the reader was on. */
  const wanted = state.picked ?? panel.current;
  const view = browser(popup, {
    root: pane,
    rows: offered,
    /* Engines in their own order, each under its caption — only the
       ones that ANSWERED: a provider with nothing to offer is a row
       that cannot be played, and the providers tab is where it is
       dealt with. A filter narrows further: an engine with no match
       drops out rather than captioning an empty stretch. */
    groupOf: (entry) => entry.engine,
    drawGroup: engineHeading,
    drawRow: (entry) => modelRow(entry, panel.current),
    drawPreview: (entry) => modelDetail(pane, entry, panel.current, { use, setLoaded }),
    onOpen: use,
    onMove: (entry) => (state.picked = `${entry.engine.name}/${entry.model.name}`),
    onKey: (event, entry) => {
      if (event.key !== "l" && event.key !== "u") return false;
      guard(setLoaded)(entry, event.key === "l");
      return true;
    },
    /* Nothing to play: either the filter is too narrow, or no provider
       has answered yet — and the way out of the second one is the tab
       beside this list. */
    empty: (filtered) =>
      filtered
        ? { line: "No model matches that.", hint: "clear the filter, or set up a provider" }
        : { line: "No model yet.", hint: "start a local engine, or set up a provider" },
  });
  // Open where the reader was — or on the model the session is playing,
  // the way back to it.
  view.select((entry) => `${entry.engine.name}/${entry.model.name}` === wanted);

}

function modelRow(entry, current) {
  const lamp = span("otk-row__lamp", "");
  const managed = entry.model.can_load_unload;
  if (managed && entry.model.loaded) lamp.append(span("otk-dot otk-dot--sm", ""));
  const button = row(
    lamp,
    span("otk-row__title", entry.model.name),
    span("otk-row__num otk-row__num--size", entry.model.size),
    span("otk-row__num otk-row__num--count", entry.model.context),
  );
  button.classList.add("otk-row--indent", "otk-row--mono");
  /* Bold is loaded, dim is not — and only where loading is a thing
     that happens. A cloud model is always "loaded" in the sense the
     payload means it, so weighting it would say something about it
     that is not true of anything. */
  button.classList.toggle("is-loaded", managed && entry.model.loaded);
  button.classList.toggle("is-dim", managed && !entry.model.loaded);
  if (`${entry.engine.name}/${entry.model.name}` === current) button.append(span("otk-tag", "chosen"));
  return button;
}

function modelDetail(pane, entry, current, { use, setLoaded }) {
  const managed = entry.model.can_load_unload;
  const where = entry.engine.local ? "on this machine" : "over the wire";
  const state = !managed ? "" : entry.model.loaded ? " · loaded" : " · not loaded";
  const chosen = `${entry.engine.name}/${entry.model.name}` === current;

  const facts = element("div", "otk-detail__section");
  if (entry.model.size) facts.append(fact("size", entry.model.size));
  if (entry.model.context) facts.append(fact("context", entry.model.context));
  facts.append(fact("provider", entry.engine.label));

  // Pinned under the pane: the row above is a name of any length, and
  // the button must not move with it.
  const verbs = [
    actionButton("Use for this story", {
      kind: "otk-btn--primary",
      onclick: guard(() => use(entry)),
    }),
  ];
  if (managed) {
    verbs.push(
      actionButton(entry.model.loaded ? "Unload" : "Load", {
        onclick: guard(() => setLoaded(entry, !entry.model.loaded)),
      }),
      element(
        "p",
        "otk-note otk-actions__note",
        "A model can be chosen without being loaded; the engine loads it on the first reply.",
      ),
    );
  }
  $("[data-actions]", pane).replaceChildren(...verbs);

  return [
    span("otk-label otk-label--accent", `${where}${state}`),
    element("h3", "otk-detail__title", entry.model.name),
    chosen && element("p", "otk-note otk-accent-ink", "chosen for this story"),
    facts,
  ].filter(Boolean);
}

function engineHeading(engine) {
  /* A caption per engine: the lamp, its name, and what it holds. */
  const heading = element("h3", "otk-group");
  heading.append(
    element("span", engine.connected ? "otk-dot" : "otk-dot otk-dot--off"),
    span("otk-group__name", engine.label),
    span("otk-group__count", `${engine.models.length} ${engine.local ? "on this machine" : "over the wire"}`),
  );
  return [heading, element("div", "otk-rule")];
}

// ---------- the providers tab ----------

function buildProviders(state, notice) {
  const { popup, panel } = state;
  const pane = $('[data-pane="providers"]', popup);
  const answering = panel.engines.filter((engine) => engine.connected);
  $("[data-tabs-aside]", popup).textContent =
    `${answering.length} of ${panel.engines.length} answering`;
  footnote(popup, notice || `${answering.length} ${answering.length === 1 ? "provider" : "providers"} answering`);

  /* In the ENGINES' own order, which is the registry's
     (`providers.registry.CLIENTS`) — the same order the terminal's
     picker lists them in. A frontend that re-sorted them would be
     inventing an order the other frontend does not have. */
  const rows = panel.engines.map((engine) => ({ engine, haystack: engine.label.toLowerCase() }));
  // Read before the paint, for the same reason the models tab does.
  const wanted = state.pickedProvider;

  const view = browser(popup, {
    root: pane,
    rows,
    drawRow: (entry) => {
      const stack = element("span", "otk-stack");
      stack.append(
        span("otk-choice__name", entry.engine.label),
        span("otk-index__sub", entry.engine.url),
      );
      return row(
        element("span", entry.engine.connected ? "otk-dot" : "otk-dot otk-dot--off"),
        stack,
        span("otk-row__num", entry.engine.connected ? "answering" : "not answering"),
      );
    },
    drawPreview: (entry) => providerDetail(state, pane, entry.engine),
    onOpen: () => $("[data-detail] input", pane)?.focus(),
    onMove: (entry) => (state.pickedProvider = entry.engine.name),
  });
  // A rebuild — a save's, a test's, a tab switched away and back —
  // stays on the provider it was about.
  if (wanted) view.select((entry) => entry.engine.name === wanted);
}

function providerDetail(state, pane, engine) {
  const models = engine.models.length;
  const head = span(
    "otk-label",
    engine.connected ? `answering · ${models} ${models === 1 ? "model" : "models"}` : "not answering",
  );

  const fields = element("div", "otk-detail__section");
  const url = urlField(state, engine);
  const key = keyField(state, engine);
  fields.append(span("otk-margin__key", "url"), url);
  fields.append(span("otk-margin__key", "api key"), key);
  fields.append(
    element(
      "p",
      "otk-note",
      "The key is kept in the state dir on this machine and sent only to this provider.",
    ),
  );

  const save = actionButton("Save", {
    kind: "otk-btn--primary",
    onclick: guard(() => saveProvider(state, engine)),
  });
  // Nothing typed is nothing to save: the button is a door that does
  // something, and a door that does nothing should not look like one.
  save.setAttribute("aria-disabled", "true");
  const settle = () => save.setAttribute("aria-disabled", String(!dirty(state.popup, engine)));
  for (const input of [url, key]) input.addEventListener("input", settle);
  $("[data-actions]", pane).replaceChildren(
    save,
    actionButton("Test connection", { onclick: guard(() => testProvider(state, engine)) }),
  );

  return [head, element("h3", "otk-detail__title", engine.label), fields];
}

function urlField(state, engine) {
  /* A local URL is editable — a port moves. A cloud URL is the
     provider's own and shown dim, because reading it is useful and
     changing it is not. */
  const input = element("input", "otk-field otk-field--mono");
  input.type = "url";
  input.dataset.provider = "url";
  input.value = engine.url;
  input.disabled = !engine.local;
  if (engine.local) saveOnEnter(state, input, engine, "url");
  return input;
}

// What a key that is SET looks like: six characters, so the box reads as
// full. The value never arrives on this side, so these stand for it —
// and, being a stand-in, they are cleared the moment the field is
// entered and are never saved back.
const _MASK = "••••••";

// How long "Checking" stands before it is allowed to become the answer.
// A reader who pressed Test has to see that the question was asked.
const _ASKING_MS = 1000;

const _beat = (ms) => new Promise((wake) => setTimeout(wake, ms));

function keyField(state, engine) {
  /* One shape whether a key is set or not: a password field, empty for
     a provider with no key and masked for one that has it. Typing
     replaces the key; typing nothing changes nothing. */
  const input = element("input", "otk-field otk-field--mono");
  input.type = "password";
  input.dataset.provider = "api_key";
  if (engine.has_key) {
    const mask = () => {
      input.value = _MASK;
      input.dataset.mask = "yes";
    };
    mask();
    // Entering the field clears the stand-in so a new key can be typed;
    // leaving it without typing one puts it back, because the key is
    // still there and a field that went empty would say it is not.
    input.addEventListener("focus", () => {
      if (!input.dataset.mask) return;
      delete input.dataset.mask;
      input.value = "";
    });
    input.addEventListener("blur", () => {
      if (!input.value) mask();
    });
  }
  saveOnEnter(state, input, engine, "api_key");
  return input;
}

function saveOnEnter(state, input, engine, attr) {
  /* Enter saves the field it is in, as the Save button saves both. A
     field left without saving is left alone: a half-typed URL must not
     become the configuration because the reader clicked elsewhere. */
  input.addEventListener(
    "keydown",
    guard(async (event) => {
      /* Esc unwinds one layer, innermost first: the field the reader is
         typing in, not the list behind it and not the panel behind
         that. Stopped here, or the dialog's own cancel would take a
         half-typed api key and the whole picker with it. */
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        input.value = attr === "url" ? engine.url : "";
        $("[data-list]", input.closest("dialog"))?.focus();
        return;
      }
      if (event.key !== "Enter") return;
      event.preventDefault();
      /* A field left empty is a field nobody filled in: it must not
         clear the url a provider is reached at, or the key it is
         reached with — and the mask standing in for a key is not a key
         either. */
      if (!input.value.trim() || input.dataset.mask) return;
      const { notice } = await api.saveProviderField(engine.name, attr, input.value);
      await refreshProvider(state, engine, notice);
    }),
  );
}

function dirty(popup, engine) {
  /* What a save would actually write: a url that differs from the
     configured one, or a key that is not the stand-in. Nothing else
     counts — the mask is not a key, and an untouched field is not an
     edit. */
  const url = $('[data-detail] input[data-provider="url"]', popup);
  const key = $('[data-detail] input[data-provider="api_key"]', popup);
  const movedUrl = url && !url.disabled && url.value.trim() && url.value.trim() !== engine.url;
  const typedKey = key && key.value.trim() && !key.dataset.mask;
  return Boolean(movedUrl || typedKey);
}

async function saveProvider(state, engine) {
  /* The Save button: both fields at once, skipping what did not change
     — the untouched url, the mask standing in for a key that is already
     there. Saving nothing is an answer too. */
  const url = $('[data-detail] input[data-provider="url"]', state.popup);
  const key = $('[data-detail] input[data-provider="api_key"]', state.popup);
  const notices = [];
  if (url && !url.disabled && url.value.trim() && url.value.trim() !== engine.url) {
    const { notice } = await api.saveProviderField(engine.name, "url", url.value.trim());
    notices.push(notice);
  }
  if (key && key.value.trim() && !key.dataset.mask) {
    const { notice } = await api.saveProviderField(engine.name, "api_key", key.value);
    notices.push(notice);
  }
  await refreshProvider(state, engine, notices.join(" ") || "Nothing to save.");
}

function testProvider(state, engine) {
  /* The test IS the catalog read, for this one provider: a provider
     that answers with models is configured, and one that does not is
     not — no new backend door, the same read the picker draws from.

     The dialog opens FIRST, saying what is happening: a dead host
     answers by timing out, and a reader who pressed Test must not be
     left looking at an unchanged screen wondering whether it took. */
  const dialog = $('dialog[data-dialog="told"]');
  const answered = ask("told", () => {
    $("[data-title]", dialog).textContent = "Checking";
    $(".otk-dialog__body", dialog).textContent = `Asking ${engine.label} at ${engine.url}…`;
  });
  // A local engine answers in milliseconds, and a question that is asked
  // and answered inside one frame reads as nothing having happened: the
  // asking stands long enough to be read.
  const asking = Promise.all([api.provider(engine.name), _beat(_ASKING_MS)]).then(([fresh]) => fresh);
  asking.then(
    guard((fresh) => {
      const found = fresh.engines.find((entry) => entry.name === engine.name);
      patch(state, engine, found);
      const models = found?.models.length ?? 0;
      // The dialog the reader is already looking at becomes the answer.
      $("[data-title]", dialog).textContent = found?.connected ? "Connected" : "No answer";
      $(".otk-dialog__body", dialog).textContent = found?.connected
        ? `${engine.label} answered with ${models} ${models === 1 ? "model" : "models"}.`
        : `${engine.label} did not answer at ${engine.url}.`;
    }),
  );
  // The list catches up once the reader is done with the answer: a
  // rebuild under an open dialog would take the focus out from under it.
  return answered.then(() => state.build("providers", ""));
}

async function refreshProvider(state, engine, notice) {
  /* One provider re-asked and patched into the panel, wherever it now
     stands — the terminal's own one-provider refresh, over the wire. */
  const fresh = await api.provider(engine.name);
  patch(state, engine, fresh.engines.find((entry) => entry.name === engine.name));
  state.build("providers", notice);
}

function patch(state, engine, found) {
  /* One provider's row replaced in place — the rest of the panel is
     what it was, and the list keeps its order and its cursor. */
  if (!found) return;
  state.panel = {
    ...state.panel,
    engines: state.panel.engines.map((entry) => (entry.name === engine.name ? found : entry)),
  };
}

function fact(key, value) {
  const line = element("p", "otk-fact");
  line.append(span("", key), span("", value));
  return line;
}
