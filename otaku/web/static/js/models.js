/* The model picker: every catalog otaku can reach, and the providers
   behind them — the grouped shape of `browser()`, a caption per engine
   with the models walked past them. Beside it, the panel that
   configures an engine: the only screen that WRITES to something other
   than the story, which is why it is drawn once per open and not per
   row — a half-typed key must survive the cursor moving.

   An api key's VALUE never arrives on this side; only whether one is
   set. */

import * as api from "./api.js";
import { browser, closeAll, footnote, guard, popups, wiring } from "./browser.js";
import { $, element, row, span } from "./dom.js";
import { landed } from "./shell.js";
import { tell } from "./transcript.js";

export async function openModels(answered = "") {
  if (answered) tell(answered);
  const popup = popups.get("/model");
  const panel = await api.providers();
  const list = $(".otk-list", popup);
  const load = $("[data-load]", popup);
  const unload = $("[data-unload]", popup);
  // Every model that can be played, flat and in list order, so the
  // arrows can walk them past the group captions between them.
  const offered = panel.engines.flatMap((engine) =>
    engine.models.map((model) => ({ engine, model, haystack: model.name.toLowerCase() })),
  );

  const use = async (entry) => {
    const { notice } = await api.act("switch-model", {
      provider: entry.engine.name,
      model: entry.model.name,
    });
    closeAll();
    await landed(notice, { redraw: "always" });
  };

  const setLoaded = async (entry, wanted) => {
    if (!entry?.model.can_load_unload) return;
    const { notice } = await api.act("load-model", {
      provider: entry.engine.name,
      model: entry.model.name,
      loaded: wanted,
    });
    openModels(notice);
  };

  drawProviders(popup, panel);
  // The footer is the machine's gauge and nothing else: what a load or
  // a switch answered goes under the prompt, where every other answer
  // goes (`transcript.tell`).
  footnote(popup, panel.memory || `${panel.engines.length} providers configured`);

  if (!offered.length) {
    // Nothing answered anywhere: no rows to browse, so the empty state
    // takes the list's place and the panel beside it stays the way out.
    // The wiring still turns, or the last open's listeners would keep
    // answering the keys over rows that are no longer there.
    wiring(popup);
    list.replaceChildren(noModels());
    popup.showModal();
    return;
  }

  const view = browser(popup, {
    rows: offered,
    /* Engines in their own order, each under its caption — only the
       ones that ANSWERED: a provider with nothing to offer is a row
       that cannot be played, and the panel on the right is where it is
       dealt with. A filter narrows further: an engine with no match
       drops out rather than captioning an empty stretch. */
    groupOf: (entry) => entry.engine,
    drawGroup: engineHeading,
    drawRow: (entry) => modelRow(entry, panel.current),
    onOpen: use,
    /* Load and unload act on the highlighted row, and only where
       loading is a thing that happens: the one that applies is the one
       the model is not. */
    onMove: (entry) => {
      const managed = Boolean(entry?.model.can_load_unload);
      if (load) load.disabled = !managed || entry.model.loaded;
      if (unload) unload.disabled = !managed || !entry.model.loaded;
    },
    onKey: (event, entry) => {
      if (event.key !== "l" && event.key !== "u") return false;
      guard(setLoaded)(entry, event.key === "l");
      return true;
    },
  });
  // Open on the model the session is playing — the way back to it.
  view.select((entry) => `${entry.engine.name}/${entry.model.name}` === panel.current);

  if (load) load.onclick = guard(() => setLoaded(view.current(), true));
  if (unload) unload.onclick = guard(() => setLoaded(view.current(), false));
  popup.showModal();
}

function modelRow(entry, current) {
  const button = row(
    span("otk-row__text", entry.model.name),
    span("otk-row__col otk-row__col--size", entry.model.size),
    span("otk-row__col otk-row__col--context", entry.model.context),
  );
  /* Bold is loaded, dim is not — and only where loading is a thing
     that happens. A cloud model is always "loaded" in the sense the
     payload means it, so weighting it would say something about it
     that is not true of anything. */
  const weighed = entry.model.can_load_unload;
  button.classList.toggle("is-loaded", weighed && entry.model.loaded);
  button.classList.toggle("is-dim", weighed && !entry.model.loaded);
  return button;
}

function engineHeading(engine) {
  /* A caption per engine: its name over its models. Whether it answered
     is the panel's to say — every engine has a card there, and only the
     ones that answered have rows here. */
  const heading = element("h3", "otk-group");
  heading.append(span("otk-label", engine.label));
  return heading;
}

function noModels() {
  /* Nothing answered anywhere. The empty state says what otaku tried,
     and leaves the reader two doors: start an engine, or paste a key —
     which is the panel on the right. */
  const box = element("div", "otk-empty");
  const again = element("button", "otk-btn", "Look again");
  again.type = "button";
  again.onclick = () => openModels();
  box.append(
    element("p", "otk-empty__title", "No models yet."),
    element(
      "p",
      "otk-preview__body",
      "otaku looked for a local backend on the usual ports and found nothing answering. " +
        "Start one, or paste a key for a cloud provider on the right.",
    ),
    again,
  );
  return box;
}

function drawProviders(popup, panel) {
  /* One card per engine: whether it answered, where it is, and whether
     it has a key. An api key's VALUE never arrives here — only whether
     one is set — so a card can never show it. */
  const out = [element("h3", "otk-label", "Providers")];
  for (const engine of panel.engines) out.push(providerCard(engine));
  $(".otk-preview", popup).replaceChildren(...out);
}

function providerCard(engine) {
  /* The dot says whether it answered and nothing says it twice. Both
     fields are here for every provider — a local engine can want a key
     as much as a cloud one, and a field that is missing is a question
     the reader has to take to a config file. */
  const card = element("div", "otk-provider");
  const head = element("div", "otk-provider__head");
  head.append(span("otk-provider__name", engine.label));
  head.append(element("span", engine.connected ? "otk-dot is-ok" : "otk-dot"));
  card.append(head, urlField(engine), keyField(engine));
  return card;
}

function urlField(engine) {
  /* A local URL is editable — a port moves. A cloud URL is the
     provider's own and shown dim, because reading it is useful and
     changing it is not. */
  const field = element("p", "otk-provider__field");
  field.append(element("span", "otk-label", "URL:"));
  const input = element("input", engine.local ? "otk-input" : "otk-input is-dim");
  input.type = "url";
  input.value = engine.url;
  input.disabled = !engine.local;
  if (engine.local) saveOn(input, engine, "url");
  field.append(input);
  return field;
}

// What a key that is SET looks like: six characters, so the box reads as
// full. The value never arrives on this side, so these stand for it —
// and, being a stand-in, they are cleared the moment the field is
// entered and are never saved back.
const _MASK = "••••••";

function keyField(engine) {
  /* One shape whether a key is set or not: a password field, empty for
     a provider with no key and masked for one that has it. Typing
     replaces the key; typing nothing changes nothing. */
  const field = element("p", "otk-provider__field");
  field.append(element("span", "otk-label", "API key:"));
  const input = element("input", "otk-input");
  input.type = "password";
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
  saveOn(input, engine, "api_key");
  field.append(input);
  return field;
}

function saveOn(input, engine, attr) {
  /* Enter saves, as the footer says. A field left without saving is
     left alone: a half-typed URL must not become the configuration
     because the reader clicked elsewhere. */
  input.addEventListener("keydown", guard(async (event) => {
    /* Esc unwinds one layer, innermost first: the field the reader is
       typing in, not the filter behind it and not the screen behind
       that. Stopped here, or the dialog's own cancel would take a
       half-typed api key and the whole picker with it. */
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      input.value = attr === "url" ? engine.url : "";
      $(".otk-list", input.closest("dialog"))?.focus();
      return;
    }
    if (event.key !== "Enter") return;
    event.preventDefault();
    /* A field left empty is a field nobody filled in: it must not clear
       the url a provider is reached at, or the key it is reached with —
       and the mask standing in for a key is not a key either. */
    if (!input.value.trim() || input.dataset.mask) return;
    const { notice } = await api.act("save-field", {
      provider: engine.name,
      field: attr,
      value: input.value,
    });
    openModels(notice);
  }));
}
