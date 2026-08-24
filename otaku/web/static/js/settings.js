/* The settings form: the /set family as controls — the effort ladder as
   a segmented control, a switch per toggle, a field row per inference
   parameter. Every knob is also a /set command, and every write here IS
   one: the form posts the command line and redraws from the answer, so
   the panel and the typed form can never disagree. */

import * as api from "./api.js";
import { editingKeys, footnote, guard, hint, popups, wiring } from "./browser.js";
import { $, $$, element, fieldRow, span } from "./dom.js";

// What a parameter nobody has set reads as — the model's own value,
// which is an absence and is drawn like one.
const DEFAULT_VALUE = "default";

export async function openSettings(answered = "") {
  const popup = popups.get("/set");
  const knobs = await api.settings();

  const think = formSection("Think", "session-wide");
  const segmented = element("div", "otk-segmented");
  segmented.setAttribute("role", "radiogroup");
  for (const level of knobs.think_levels) {
    const option = element("button", "otk-segmented__opt", level);
    option.type = "button";
    option.setAttribute("role", "radio");
    option.setAttribute("aria-checked", String(level === knobs.think));
    option.classList.toggle("is-active", level === knobs.think);
    option.onclick = guard(() => runSet(`/set think ${level}`));
    segmented.append(option);
  }
  think.append(segmented);

  const toggles = formSection("Toggles", "session-wide");
  for (const [name, label, about] of [
    ["verbose", "Verbose", "the stats line after each reply"],
    ["autocorrect", "Autocorrect", "settle names to the cast's spelling"],
    ["notification", "Notification", "sound when a reply lands"],
  ]) {
    const toggle = element("button", "otk-switch");
    toggle.type = "button";
    toggle.setAttribute("role", "switch");
    toggle.setAttribute("aria-checked", String(knobs[name]));
    toggle.classList.toggle("is-on", knobs[name]);
    toggle.append(
      element("span", "otk-switch__track"),
      span("otk-switch__label", label),
      span("otk-meta", about),
    );
    toggle.onclick = guard(() => runSet(`/set ${name} ${knobs[name] ? "off" : "on"}`));
    toggles.append(toggle);
  }

  const params = formSection("Parameters", `per model · ${knobs.model || "no model"}`);
  /* The same box the lore browser's fields sit in, in the shape a column
     of numbers wants: tighter rows and a fixed value cell on the right.
     The shape belongs to the field list, not to this dialog. */
  const rows = element("div", "otk-fields otk-fields--params");
  for (const parameter of knobs.parameters) {
    // Two columns and nothing else: the name, and the value that is
    // edited by clicking it. A row that IS the control has nothing to
    // say about how to open it. A parameter nobody has set reads dim,
    // because "default" is the absence of a value and not one.
    const button = fieldRow(parameter.name, parameter.value || DEFAULT_VALUE);
    if (!parameter.value) $(".otk-field-row__value", button).classList.add("is-default");
    button.onclick = () => editParameter(button, parameter);
    rows.append(button);
  }
  params.append(rows);

  // Two columns, as the design lays a form out; they wrap on their own.
  const form = element("form", "otk-form");
  const left = element("div", "otk-form__col");
  const right = element("div", "otk-form__col");
  left.append(think, toggles);
  right.append(params);
  form.append(left, right);
  $(".otk-popup__body", popup).replaceChildren(form);
  // One slot, on the left: this panel advertises no keys, so what a
  // knob just answered goes where its standing sentence is — and the
  // sentence comes back with the next redraw.
  hint(popup, answered || "every knob here is also a /set command");
  footnote(popup, "");
  formKeys(popup);
  popup.showModal();
}

function editParameter(row, parameter) {
  /* The value is edited where it is read: the row's own field, no panel
     and nothing moved. Enter saves — and an EMPTY field saves the
     MODEL's default back, which is the only reset there is now that the
     row says nothing else. Esc and any click elsewhere cancel, a click
     on another parameter included, which then opens its own field. */
  const editing = element("div", "otk-field-row is-editing");
  const input = element("input", "otk-input");
  input.type = "text";
  input.value = parameter.value;
  input.placeholder = DEFAULT_VALUE;
  editing.append(span("otk-field-row__name", parameter.name), input);
  row.replaceWith(editing);
  input.focus();
  input.select();
  editingKeys(input, {
    saves: (event) => event.key === "Enter",
    save: () =>
      guard(runSet)(`/set parameter ${parameter.name} ${input.value.trim() || "reset"}`),
    cancel: () => {
      editing.replaceWith(row);
      row.focus();
    },
  });
}

function formKeys(popup) {
  /* The keys the footer promises. A form is a column of controls, so
     "navigate" is moving focus between them and "edit" is pressing the
     one you are on — which is what a button does by itself, once
     something is focused. Without this the panel opens with `close ·
     esc` focused and Enter shuts it. */
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
  /* Not the close button, which is what `showModal` would otherwise
     focus — and then Enter would close the panel the footer just told
     the reader to edit in. Focused outright as well as marked: every
     control here is a write, and a write rebuilds the form, which drops
     the focused control and with it the whole keyboard —
     `showModal` on an already-open dialog honours no autofocus. */
  const first = controls()[0];
  first?.setAttribute("autofocus", "");
  first?.focus();
}

async function runSet(line) {
  const { notice } = await api.runCommandLine(line);
  openSettings(notice);
}

function formSection(label, note) {
  const box = element("div", "otk-form__section");
  const head = element("div", "otk-form__head");
  head.append(span("otk-label", label), span("otk-form__note", note));
  box.append(head);
  return box;
}
