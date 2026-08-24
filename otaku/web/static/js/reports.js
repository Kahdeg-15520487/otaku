/* The report panel: one dialog, four reports, a body shape each — the
   window diagram over the wire, the table of what tokens went on, and
   the definition list twice. Every number and every sentence in them is
   the backend's (`api.reports`); which shape carries it is the
   design's. */

import * as api from "./api.js";
import { footnote, guard, hint, popups } from "./browser.js";
import { $, element, span } from "./dom.js";
import { count } from "./format.js";
import { tell } from "./transcript.js";

export async function openContext() {
  const preview = await api.context();
  const shape = preview.shape;
  const out = [drawWindow(shape), element("p", "otk-report-body__lede", preview.lede)];
  for (const part of preview.parts) {
    out.push(element("p", "otk-role", part.role));
    out.push(element("p", "otk-verbatim", part.body));
  }
  showPanel(
    "context",
    "Context preview",
    out,
    `~${count(shape.total_tokens)} tokens · ${shape.used}% of ${count(shape.context_max)}`,
  );
}

function drawWindow(shape) {
  /* What the request is MADE of, at a glance: the verbatim head and
     tail with the summarized middle standing between them. A story
     short enough to be sent whole has no middle and no diagram to
     draw — one segment says the whole truth. */
  const box = element("div", "otk-window");
  box.setAttribute("aria-label", "Context window shape");
  const segment = (modifier, n, caption) => {
    const seg = element("div", `otk-window__seg otk-window__seg--${modifier}`);
    seg.append(span("otk-window__n", n), span("otk-window__cap", caption));
    return seg;
  };
  if (!shape.middle) {
    box.append(segment("verbatim", String(shape.kept), "verbatim"));
    return box;
  }
  const summaries = shape.rolled_up
    ? `${shape.summaries} scene summaries + a rollup`
    : `${shape.summaries} scene summaries`;
  box.append(
    segment("verbatim", String(shape.head), "verbatim"),
    segment("summarized", summaries, `${count(shape.middle)} messages in between`),
    segment("verbatim", String(shape.tail), "verbatim"),
  );
  return box;
}

export async function openUsage(argument = "") {
  const scope = argument.trim();
  const report = await api.usage(scope);
  /* A refusal is the whole answer — no story yet, nothing recorded, an
     argument the backend does not know — and here it is shown IN the
     panel rather than in the flow behind it: this report has two
     scopes, and the tab beside the empty one is the way to the other. */
  if (report.notice) {
    showPanel("usage", "Token usage", [element("p", "otk-report-body__lede", report.notice)]);
    scopeTabs(report.scopes, scope);
    return;
  }
  const table = element("div", "otk-table");
  table.setAttribute("role", "table");
  table.setAttribute("aria-label", "Token usage");
  let purpose = null;
  for (const row of report.rows) {
    if (row.purpose !== purpose) {
      purpose = row.purpose;
      table.append(tableRow("head", [purpose, "REQS", "PROMPT", "REPLY", "TOK/S"]));
    }
    table.append(
      tableRow("", [
        `${row.provider} · ${row.model}`,
        count(row.requests),
        count(row.prompt_tokens),
        count(row.completion_tokens),
        row.rate.toFixed(1),
      ]),
    );
  }
  table.append(
    tableRow("total", [
      "total",
      count(report.requests),
      count(report.prompt_tokens),
      count(report.completion_tokens),
      "—",
    ]),
  );
  showPanel("usage", "Token usage", [table], `${report.scope} · ${count(report.total_tokens)} tokens`);
  scopeTabs(report.scopes, scope);
}

function scopeTabs(scopes, current) {
  /* The scopes a report can be asked for, as the design's tabs over its
     table. Their words are the BACKEND's — the same two the report says
     about itself — so a tab and the footer under it can never disagree.
     Drawn after `showPanel`, which empties the strip for every report
     that has no scopes to offer. */
  const panel = popups.get("/report");
  const strip = $("[data-scopes]", panel);
  if (!strip) return;
  strip.replaceChildren(
    ...(scopes ?? []).map(({ key, label }) => {
      const tab = element("button", "otk-tab", label.charAt(0).toUpperCase() + label.slice(1));
      tab.type = "button";
      tab.setAttribute("role", "tab");
      const active = key === current;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
      tab.onclick = guard(() => openUsage(key));
      return tab;
    }),
  );
  strip.hidden = !strip.childElementCount;
}

function tableRow(modifier, cells) {
  const row = element("div", modifier ? `otk-table__row otk-table__row--${modifier}` : "otk-table__row");
  row.setAttribute("role", "row");
  for (const cell of cells) {
    const box = span("", cell);
    box.setAttribute("role", modifier === "head" ? "columnheader" : "cell");
    row.append(box);
  }
  return row;
}

export async function openBalance() {
  const report = await api.balance();
  if (report.notice) {
    tell(report.notice);
    return;
  }
  showPanel("balance", "Balance", [
    defs(
      report.rows.map((row) => [row.label, row.value]),
      "otk-defs--figures",
    ),
  ]);
}

export async function openInfo() {
  const report = await api.info();
  const blocks = [];
  for (const section of report.sections) {
    // A block with no facts to give says why in a sentence of its own.
    if (section.note) blocks.push(element("p", "otk-report-body__lede", section.note));
    if (section.rows.length) blocks.push(defs(section.rows));
  }
  showPanel("info", "Info", blocks);
}

function defs(rows, modifier = "") {
  const list = element("dl", `otk-defs ${modifier}`.trim());
  for (const [label, value] of rows) {
    list.append(element("dt", "", label), element("dd", "", value));
  }
  return list;
}

/* What each report is worth in width, on the panel family's own ladder:
   a balance of four lines and a preview of the whole wire are the same
   dialog and must not be the same box. `--steady` holds usage still
   while its two scopes are switched between. */
const _PANEL_SIZE = {
  balance: ["otk-popup--narrow"],
  usage: ["otk-popup--reading", "otk-popup--steady"],
  info: ["otk-popup--wide"],
  context: ["otk-popup--verbatim"],
};
const _SIZES = [...new Set(Object.values(_PANEL_SIZE).flat())];

function showPanel(kind, title, blocks, note = "") {
  const panel = popups.get("/report");
  // One dialog, four reports: the kind is on the panel so a screen can
  // tell them apart, and the size class is what the stylesheet reads.
  panel.dataset.report = kind;
  panel.classList.remove(..._SIZES);
  panel.classList.add(...(_PANEL_SIZE[kind] ?? ["otk-popup--reading"]));
  // The left slot names the command this panel IS — every report here
  // is one, and the kind is its token without the slash. Not the keys:
  // esc closes every dialog in the app and needs saying nowhere.
  hint(panel, `/${kind} command`);
  // A report with scopes fills this in after; one without shows none,
  // and never the last report's.
  const strip = $("[data-scopes]", panel);
  if (strip) {
    strip.replaceChildren();
    strip.hidden = true;
  }
  $("[data-title]", panel).textContent = title;
  $(".otk-report-body", panel).replaceChildren(...blocks);
  // The footer's right-hand stat belongs to a report that knows its own
  // numbers; a report with none leaves it empty rather than saying
  // something the body does not.
  footnote(panel, note);
  panel.showModal();
}
