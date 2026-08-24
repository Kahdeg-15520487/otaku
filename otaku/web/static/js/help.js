/* The help screen: every command in the shared table, in two columns.

   It is a reference sheet, not a menu — nothing here is a control. The
   rail carries the buttons and the composer takes the typed lines; this
   page exists to be READ, so a row is a row: it lights under the pointer
   because that is how a reader keeps their place in a long table, and
   that is all it does.

   The rows, the group names and the prose explainer are read from
   `table.js` — the language's one home on this side — and the filter's
   keys are the kit's (`browser.wireFilter`): `/` goes to the filter,
   Esc empties it before it closes anything. */

import { wireFilter, wiring } from "./browser.js";
import { $, element, span } from "./dom.js";
import { allSpecs, groups, prose } from "./table.js";

export function openHelp() {
  const popup = $('dialog[data-popup="/help"]');
  const scroller = $(".otk-help", popup);
  const columns = $(".otk-help__columns", popup);
  const rows = _rows();
  let shown = rows;

  const signal = wiring(popup);

  function paint() {
    const grouped = [];
    for (const row of shown) {
      if (!grouped.length || grouped.at(-1).group !== row.group) {
        grouped.push({ group: row.group, members: [] });
      }
      grouped.at(-1).members.push(row);
    }
    columns.replaceChildren(...grouped.map(drawGroup));
  }

  function drawGroup({ group, members }) {
    const box = element("div", "otk-help__group");
    box.append(element("p", "otk-label", groups()[group]));
    box.append(...members.map(drawRow));
    return box;
  }

  function drawRow(row) {
    const el = element("div", "otk-help__row");
    if (row.prose) el.classList.add("otk-help__row--prose");
    // Token and argument shape are ONE label, as the terminal's help
    // spells them: what a command takes belongs beside its name, not in
    // a column of its own — and the sentence gets the room back.
    const label = element("span", "otk-help__label");
    label.append(span("otk-help__token", row.token));
    if (row.args) label.append(" ", span("otk-help__args", row.args));
    el.append(label, span("otk-help__desc", row.description));
    return el;
  }

  function refilter(raw) {
    const needle = raw.trim().toLowerCase();
    shown = needle ? rows.filter((row) => row.haystack.includes(needle)) : rows;
    paint();
  }

  wireFilter(popup, { refilter, focus: () => scroller.focus() }, signal);
  paint();
  /* `showModal` focuses the first focusable descendant — the filter —
     unless something claims it with `autofocus`. The table is what the
     reader came for and it is long enough to scroll, so the scroller
     takes the focus and the arrows scroll it.  */
  scroller.setAttribute("autofocus", "");
  popup.showModal();
  scroller.focus();
}

function _rows() {
  /* Every row the screen shows, flattened once: the shared table's, with
     the prose row inserted at the head of the group it opens. */
  const out = [];
  let group = null;
  const explainer = prose();
  for (const command of allSpecs()) {
    if (command.group !== group) {
      group = command.group;
      if (explainer && group === explainer.group) out.push(_row(explainer, true));
    }
    out.push(_row(command, false));
  }
  return out;
}

function _row(command, isProse) {
  const token = command.token ?? command.label;
  return {
    token,
    args: command.args ?? "",
    description: command.description,
    group: command.group,
    // Prose is not a command and an inline row (`… /cue`) closes a line
    // rather than opening one; both are still written down here,
    // because both are part of the language.
    prose: isProse,
    haystack: `${token} ${command.args ?? ""} ${command.description}`.toLowerCase(),
  };
}
