/* The settings docket: the /set family as a slip of leaders — the value
   each knob stands at on the right, and under it the other values it
   could take. There is no control here that is not one of those words:
   clicking a word sets it, which is exactly what typing the command
   does, because the click puts the same value through the same setter
   and redraws from its answer. The slip and the typed form can never
   disagree.

   Two blocks, because where a value persists is a real distinction: the
   session's own toggles, and the parameters kept per model. */

import * as api from "./api.js";
import { editable, footnote, guard, popups, wiring } from "./browser.js";
import { $, $$, element, span } from "./dom.js";

// What a knob nobody has set reads as — the model's own value, or its
// whole window. Either is an absence, and is drawn like one.
const DEFAULT_VALUE = "default";

export async function openSettings(answered = "") {
  const popup = popups.get("/set");
  if (!popup.open) popup.showModal();
  const knobs = await api.settings();

  const global = element("div", "otk-v otk-v--md");
  global.append(section("Global", "every story"));

  // The effort ladder: the value it stands at, and every step it could
  // take written under it in the table's own order.
  global.append(
    knob(
      leader("think", knobs.think),
      ladder(knobs.think_levels, knobs.think, (level) => setKnob("think", level)),
    ),
  );

  for (const name of ["verbose", "autocorrect", "notification"]) {
    global.append(
      knob(
        leader(name, toggle(knobs[name], (wanted) => setKnob(name, wanted))),
        element("p", "otk-note", about(name)),
      ),
    );
  }

  /* One number, edited where it is read. No cap is the model's whole
     window, which the backend spells 0 — an absence, so the field is
     EMPTY and says `default` the way an unset parameter does. Clearing
     it sets it: 0 goes out, and the same absence comes back. */
  const limit = editableLeader(
    "max_context",
    knobs.max_context ? String(knobs.max_context) : "",
    (value) => setKnob("max_context", value.trim() || "0"),
  );
  limit.lastElementChild.placeholder = DEFAULT_VALUE;
  global.append(knob(limit, element("p", "otk-note", about("max_context"))));

  const perModel = element("div", "otk-v otk-v--md");
  perModel.append(section(knobs.model || "no model", "this model"));
  const params = element("div", "otk-v otk-v--sm");
  for (const parameter of knobs.parameters) {
    // A parameter nobody has set stands at the model's own value. That is
    // an absence, so it is the field's PLACEHOLDER and not its text — and
    // it reads the same whether it was never set or was just cleared.
    const line = editableLeader(parameter.name, parameter.value, (value) =>
      setParameter(parameter.name, value.trim()),
    );
    line.lastElementChild.placeholder = DEFAULT_VALUE;
    params.append(line);
  }
  perModel.append(params);

  $("[data-knobs]", popup).replaceChildren(global, element("div", "otk-rule--double"), perModel);
  footnote(popup, answered);
  knobKeys(popup);
}

function section(name, count) {
  const head = element("div", "otk-section", name);
  head.append(span("otk-section__count", count));
  return head;
}

function knob(line, aside) {
  const box = element("div", "otk-v otk-v--xs");
  box.append(line, aside);
  return box;
}

function leader(label, value, kind = "") {
  const line = element("div", "otk-leader");
  line.append(span("", label), value instanceof Node ? value : span(kind, String(value)));
  return line;
}

function ladder(levels, current, set) {
  /* Every step the knob can take, in the shared table's own order — the
     one it stands at marked, the rest a click away. */
  const aside = element("span", "otk-leader__aside");
  levels.forEach((level, i) => {
    if (i) aside.append(" · ");
    const step = element("button", "otk-step", level);
    step.type = "button";
    step.setAttribute("aria-checked", String(level === current));
    step.setAttribute("role", "radio");
    step.onclick = guard(() => set(level));
    aside.append(step);
  });
  return aside;
}

function toggle(on, set) {
  /* on/off written out, the one in force marked: the value is a word,
     and the word is the control. */
  const box = element("span", "otk-keys");
  for (const [word, wanted] of [
    ["on", true],
    ["off", false],
  ]) {
    if (wanted === false) box.append(span("otk-faint", "/"));
    const option = element("button", "otk-toggle", word);
    option.type = "button";
    option.setAttribute("aria-checked", String(on === wanted));
    option.onclick = guard(() => set(word));
    box.append(option);
  }
  return box;
}

function editableLeader(label, value, save) {
  /* A value edited where it is READ: the figure IS the field. A knob is
     one line long, so Enter finishes it and Esc puts it back — neither
     written down, a slip having no room to explain its own keys. */
  const row = element("div", "otk-leader");
  row.append(span("", label), editable("", { text: value, save, line: true }));
  return row;
}

/** The caption under a knob. A slip has room for a caption and not for
    a sentence: `/help` prints the table's full row for the same
    command, and this says it in the space a leader leaves. Lowercase,
    as a caption is. */
const _ABOUT = {
  verbose: "the stats line after each reply",
  autocorrect: "settle names to the cast's spelling",
  notification: "a sound when a reply lands",
  max_context: "limit the model context size",
};

function about(name) {
  return _ABOUT[name] ?? "";
}

function knobKeys(popup) {
  /* A slip is a column of controls, so the arrows move focus between
     them and Enter presses the one you are on. Without this the docket
     opens with `Close` focused and Enter shuts it. */
  const signal = wiring(popup);
  const controls = () => $$("button:not(.otk-close)", popup);
  popup.addEventListener(
    "keydown",
    (event) => {
      // ⌘R is a reload, not a reset: a key with a modifier belongs to
      // the browser, and `preventDefault` on one is taking it.
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.target.matches("input, textarea")) return;
      const all = controls();
      const at = all.indexOf(document.activeElement);
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const step = event.key === "ArrowDown" ? 1 : -1;
        all[Math.max(0, Math.min(all.length - 1, at + step))]?.focus();
      }
    },
    { signal },
  );
  /* Not the close button, which `showModal` would focus — and then
     Enter closes the docket the reader came to edit in. Focused
     outright as well as marked: every control here is a write, a write
     rebuilds the slip and drops the focused control, and an already-open
     dialog honours no autofocus. */
  const first = controls()[0];
  first?.setAttribute("autofocus", "");
  first?.focus();
}

async function setKnob(name, value) {
  /* One knob, put. The slip is rebuilt from the answer rather than
     patched: a setter may settle on a value the reader did not type,
     and the read is the only thing that knows. A REFUSAL skips the
     rebuild — a typed knob's editor must stay open with the words
     still in it (`browser.editable` reads the flag) — and the rebuild
     is awaited, so the guard on the click catches a redraw that fails
     rather than leaving a stale slip with nobody told. */
  const answer = await api.setSetting(name, value);
  if (!answer.refused) await openSettings(answer.notice);
  return answer;
}

async function setParameter(name, value) {
  // An emptied field is the model's own default, which is an absence and
  // has its own door. Refusals and the redraw as `setKnob` has them.
  const answer = value ? await api.setParameter(name, value) : await api.resetParameter(name);
  if (!answer.refused) await openSettings(answer.notice);
  return answer;
}
