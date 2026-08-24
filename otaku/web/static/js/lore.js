/* The lore browser: the memory's two lenses — scenes and cast — over
   `browser()`, and the field lists their rows open into.

   Every write goes out through `api.act("edit-lore")` with the address
   the field itself carries (`kind`, `target`); the screen never invents
   one. A refusal is carried INTO the redraw as the footnote, because
   inside a popup the transcript is behind a modal, and a refusal said
   there is a refusal nobody reads. */

import * as api from "./api.js";
import { browser, footnote, inlineEditor, popups } from "./browser.js";
import { $$, element, fieldRow, row, span } from "./dom.js";
import { excerpt } from "./format.js";
import { tell } from "./transcript.js";

export async function openLore(lens = "scenes", landOn = null, answered = "") {
  const popup = popups.get("/lore");
  const memory = await api.lore();
  // The one read that can refuse: no story yet, and the answer is a
  // sentence rather than a memory to draw.
  if (memory.notice) {
    tell(memory.notice);
    return;
  }
  const tabs = $$(".otk-tab", popup);
  let showing = lens;

  let notice = answered;
  const draw = () => {
    const isScenes = showing === "scenes";
    // What a write answered with wins over the standing count once —
    // the write is why this screen is being drawn again — and the count
    // comes back the moment the reader does anything else, a lens
    // switch included.
    footnote(
      popup,
      notice ||
        `${memory.scenes.length} scene${memory.scenes.length === 1 ? "" : "s"} · ` +
          `${memory.cast.length} character${memory.cast.length === 1 ? "" : "s"}`,
    );
    notice = "";
    for (const tab of tabs) {
      const active = tab.dataset.lens === showing;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
    }
    const rows = (isScenes ? memory.scenes : memory.cast).map((item) => ({
      ...item,
      haystack: `${item.label ?? item.name} ${item.summary ?? item.description}`.toLowerCase(),
    }));
    const view = browser(popup, {
      rows,
      drawRow: (item) =>
        isScenes
          ? row(
              ...item.label
                .split(/\s{2,}/)
                .map((part, i, all) =>
                  span(i === all.length - 1 ? "otk-row__text" : "otk-row__num", part),
                ),
            )
          : row(
              span("otk-row__num otk-row__num--name", item.name),
              span("otk-row__text", item.now || ""),
            ),
      drawPreview: (item) =>
        [
          element("h3", "otk-preview__title", isScenes ? item.title || item.label : item.name),
          isScenes
            ? item.span && element("p", "otk-meta", `messages ${item.span}`)
            : item.aliases.length && element("p", "otk-meta", `aka ${item.aliases.join(", ")}`),
          element("p", "otk-preview__body", isScenes ? item.summary : item.description),
          isScenes && item.present.length && presentLine(item.present, memory.cast),
          !isScenes && item.now && element("p", "otk-meta", `now: ${item.now}`),
          ...(item.fields.length ? fieldList(item.fields, showing) : []),
        ].filter(Boolean),
      // What the footer calls the lens key. A list is not a form: with
      // the rows focused there is nothing else in here to tab to.
      onTab: () => {
        showing = isScenes ? "cast" : "scenes";
        draw();
      },
      // "→ pivot to the other side": a journal is one entry with two
      // doors, and this is the row-level one — the first field that has
      // a far side.
      onPivot: (item) => {
        const across = item.fields.find(
          (field) => field.pivot !== null && field.pivot !== undefined,
        );
        if (across) openLore(isScenes ? "cast" : "scenes", across.pivot);
      },
    });
    // Arriving by pivot: land on the row the other lens pointed at.
    if (landOn !== null) {
      view.select((item) => item.id === landOn);
      landOn = null;
    }
  };

  for (const tab of tabs) {
    tab.onclick = () => {
      showing = tab.dataset.lens;
      draw();
    };
  }
  draw();
  popup.showModal();
}

function presentLine(present, cast) {
  /* Who was in the scene, each name a door to that character — the
     journal is the same entry from the other side, and the design draws
     these as links for exactly that reason. */
  const line = element("p", "otk-meta", "present: ");
  present.forEach((name, i) => {
    if (i) line.append(", ");
    const character = cast.find((item) => item.name === name);
    if (!character) {
      line.append(name);
      return;
    }
    const link = element("button", "otk-row__pivot", name);
    link.type = "button";
    link.onclick = () => openLore("cast", character.id);
    line.append(link);
  });
  return line;
}

// A journal row is the one field two lenses share: in a scene it is a
// CHARACTER's line, in a character it is a SCENE's. Everything else
// belongs to the row being read.
const _JOURNAL = new Set(["entry", "state"]);

function fieldList(fields, lens) {
  /* Two blocks: what this row itself holds, and the journal rows it
     shares with the other lens — a scene lists its characters, a
     character lists its scenes. */
  const own = fields.filter((field) => !_JOURNAL.has(field.kind));
  const across = fields.filter((field) => _JOURNAL.has(field.kind));
  return [
    own.length && fieldBlock("Fields", own, lens),
    across.length && fieldBlock(lens === "scenes" ? "Characters" : "Scenes", across, lens),
  ].filter(Boolean);
}

function fieldBlock(heading, fields, lens) {
  /* One row per editable text, with the derived ones shown dim and
     saying why — the backend refuses them, and the screen must not
     pretend otherwise. */
  const section = element("section", "otk-preview__section");
  section.append(element("h4", "otk-label", heading));
  const box = element("div", "otk-fields");
  for (const field of fields) {
    // As much as the row can hold, cut with an ellipsis by the cell
    // itself — never wrapped, and never cut so short that the row says
    // nothing (the story browser's message rows do the same).
    const value = excerpt(field.text, 500) || "(empty)";
    if (!field.editable) {
      /* Derived, so there is nothing to save — but there is plenty to
         read: the row opens the same way an editable one does, into the
         whole text rather than the line of it that fitted. */
      const dim = fieldRow(field.label, value);
      dim.classList.add("is-dim");
      dim.onclick = () => inlineEditor(dim, { text: field.text, caption: "", readonly: true });
      box.append(dim);
      continue;
    }
    // No caption saying how to open it: the row IS the control, as the
    // settings panel's rows are.
    const button = fieldRow(field.label, value);
    button.dataset.editable = "yes";
    button.onclick = () =>
      inlineEditor(button, {
        text: field.text,
        caption: "editing field",
        save: async (text) => {
          const { notice } = await api.act("edit-lore", {
            kind: field.kind,
            target: field.target,
            text,
          });
          // Inside a popup the transcript is behind a modal, so a
          // refusal said there is a refusal nobody reads — and the
          // backend answers a refusal with a sentence like any other.
          // It is carried INTO the redraw: a screen that rebuilds on the
          // write would otherwise put its standing footnote back over
          // the answer, milliseconds after it appeared.
          openLore(lens, null, notice);
        },
      });
    box.append(button);
  }
  section.append(box);
  return section;
}
