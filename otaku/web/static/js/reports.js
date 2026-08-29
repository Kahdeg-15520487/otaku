/* The reports: the context preview as a reading panel — the request as
   a document, its stages as live figures over the wire itself — and
   usage, balance and info as torn docket slips. Every number and every
   sentence in them is the backend's (`api.reports`); which shape
   carries it is the design's.

   A slip is figures on dotted leaders, ruled where the reader should
   stop: a double rule under what is being totalled, a hairline between
   blocks. Nothing here composes prose about the product — a number is
   spelled, never editorialised. */

import * as api from "./api.js";
import { footnote, guard, popups } from "./browser.js";
import { $, element, span } from "./dom.js";
import { count } from "./format.js";

// ---------- context: the request as a document ----------

export async function openContext() {
  const popup = popups.get("/context");
  const body = $("[data-context]", popup);
  // The panel is up before its data: a click must answer NOW, and the
  // modal keeps further clicks from queueing screens behind it.
  if (!popup.open) {
    body.replaceChildren();
    footnote(popup, "");
    popup.showModal();
  }
  const preview = await api.context();
  const shape = preview.shape;

  const summary = element("div", "otk-context__summary");
  const lead = element("span", "otk-context__lead");
  lead.append(
    span("otk-context__figure", `~${count(shape.total_tokens)}`),
    span("otk-label", "tokens"),
  );
  summary.append(lead, span("otk-meta", `${shape.used}% of ${count(shape.limit)}`));
  summary.append(
    span("otk-meta otk-push", `${shape.kept} ${shape.kept === 1 ? "message" : "messages"} verbatim`),
  );

  const head = element("div", "otk-v otk-v--lg");
  head.append(summary, stages(shape));

  const wire = element("div", "otk-context__wire");
  for (const part of preview.parts) {
    const passage = element("div", "otk-passage");
    passage.append(
      span("otk-passage__rubric", part.role),
      element(
        "p",
        part.role === "user" ? "otk-prose otk-prose--said" : "otk-prose otk-prose--wire",
        part.body,
      ),
    );
    wire.append(passage);
  }

  body.replaceChildren(head, wire);
  footnote(popup, `~${count(shape.total_tokens)} of ${count(shape.limit)} tokens`);
  body.focus();
}

function stages(shape) {
  /* What the request is MADE of, at a glance: always the same four
     stages, the empty ones drawn idle — an absent stage is a fact of
     this request, not a missing drawing. */
  const strip = element("div", "otk-context__stages");
  strip.setAttribute("aria-label", "Context window shape");
  const cell = (idle, label, figure, tok) => {
    const box = element("div", idle ? "otk-context__cell otk-context__cell--idle" : "otk-context__cell");
    box.append(
      span(idle ? "otk-label" : "otk-label otk-label--ink", label),
      span("otk-context__figure", figure),
      span("otk-context__tok", tok),
    );
    return box;
  };
  strip.append(cell(!shape.head, "Head", String(shape.head), "verbatim"));
  if (shape.history) {
    const scenes = shape.rolled_up === 1 ? "scene" : "scenes";
    strip.append(cell(false, "History recap", "1", `${shape.rolled_up} ${scenes} rolled up`));
  } else {
    strip.append(cell(true, "History recap", "—", "nothing to recap"));
  }
  if (shape.summaries) {
    strip.append(
      cell(false, "Scene summaries", String(shape.summaries), `${count(shape.middle)} messages in between`),
    );
  } else {
    strip.append(cell(true, "Scene summaries", "0", "nothing summarized"));
  }
  const tailCaption =
    shape.tail_target < shape.tail_setting
      ? `verbatim · reduced from ${shape.tail_setting} to fit`
      : "verbatim";
  strip.append(cell(!shape.tail, "Tail", String(shape.tail), tailCaption));
  return strip;
}

// ---------- the dockets: usage, balance, info ----------

export async function openUsage(scope = "") {
  openSlip("usage", "Token spend");
  const report = await api.usage(scope);
  /* A refusal is the whole answer — no story yet, nothing recorded, an
     argument the backend does not know — and here it is shown IN the
     slip rather than behind it: this report has two scopes, and the tab
     beside the empty one is the way to the other. */
  if (report.notice) {
    showDocket("usage", "Token spend", [element("p", "otk-note", report.notice)]);
    scopeTabs(report.scopes, scope);
    return;
  }
  /* Spend is grouped by what ASKED for it: a pass the extractor ran is
     not a turn the reader played, and a paid provider bills both. The
     purposes are the store's own words. */
  const blocks = [];
  let purpose = null;
  for (const row of report.rows) {
    if (row.purpose !== purpose) {
      purpose = row.purpose;
      // What a purpose is CALLED comes with the row (`reports.USAGE_PURPOSES`),
      // and the count beside it is every request under it.
      const asked = report.rows
        .filter((other) => other.purpose === purpose)
        .reduce((sum, other) => sum + other.requests, 0);
      blocks.push(section(row.label, `${count(asked)} ${asked === 1 ? "request" : "requests"}`));
    }
    blocks.push(usageGroup(row));
  }
  blocks.push(element("div", "otk-rule--double"));
  const total = element("div", "otk-total");
  total.append(span("otk-label", "total"), span("otk-total__figure", count(report.total_tokens)));
  blocks.push(total);
  // The closing sentence is the report's own — the page spells no figure
  // it was not given.
  blocks.push(element("p", "otk-note", report.note));
  showDocket("usage", "Token spend", blocks, `${report.scope} · ${count(report.requests)} requests`);
  scopeTabs(report.scopes, scope);
}

function section(name, note) {
  /* A section head outranks the names beneath it: the display face over
     a rule, not a smaller caption. */
  const head = element("div", "otk-section", name);
  head.append(span("otk-section__count", note));
  return head;
}

function usageGroup(row) {
  /* One model's spend as the slip prints it: the name, the request
     count, and a dotted leader per figure. */
  const group = element("div", "otk-v otk-v--sm");
  const head = element("div", "otk-docket__row");
  head.append(
    span("otk-docket__name", `${row.provider} · ${row.model}`),
    span("otk-label", `${count(row.requests)} ${row.requests === 1 ? "req" : "reqs"}`),
  );
  group.append(
    head,
    leader("prompt", count(row.prompt_tokens)),
    leader("cached", count(row.cached_tokens)),
    leader("reply", count(row.completion_tokens)),
    leader("rate", `${row.rate.toFixed(1)} tok/s`, "otk-accent-ink"),
  );
  return group;
}

function scopeTabs(scopes, current) {
  /* The scopes a report can be asked for, as tabs over its figures.
     Their words are the BACKEND's — the same two the report says about
     itself — so a tab and the slip under it can never disagree. */
  const strip = $("[data-scopes]", popups.get("/report"));
  if (!strip) return;
  strip.replaceChildren(
    ...(scopes ?? []).map(({ key, label }) => {
      const tab = element("button", "otk-tab", label.charAt(0).toUpperCase() + label.slice(1));
      tab.type = "button";
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-selected", String(key === current));
      tab.onclick = guard(() => openUsage(key));
      return tab;
    }),
  );
  strip.hidden = !strip.childElementCount;
}

export async function openBalance() {
  openSlip("balance", "Balance");
  const report = await api.balance();
  // A refusal is the whole answer, shown IN the slip the reader opened
  // — behind the modal is where a sentence goes unread.
  if (report.notice) {
    showDocket("balance", "Balance", [element("p", "otk-note", report.notice)]);
    return;
  }
  /* Every provider with an account to bill, and what each has left. A
     row with no figure says which KIND of nothing it is — no key set,
     or an account that would not answer — because one of those is
     something the reader can act on. */
  const rows = element("div", "otk-v otk-v--sm");
  for (const row of report.rows) {
    /* Named by its CAPTION, as the terminal names it: what a provider is
       called is decided below both frontends (`reports.balances`), and
       the caption keeps the section key wherever the key is the part
       that identifies it — a self-named section reads "mine (OpenRouter)". */
    rows.append(leader(row.label, row.value, row.money ? "" : "otk-absent"));
  }
  const blocks = [element("div", "otk-hr"), rows];
  // The total is the backend's arithmetic, not the page's: it is there
  // only when one currency covers every account that answered.
  if (report.total) {
    const total = element("div", "otk-total");
    total.append(span("otk-label", "on account"), span("otk-total__figure", report.total.text));
    blocks.push(element("div", "otk-rule--double"), total);
  }
  // What the story on screen spends — the report's own sentence, which
  // is the half of "what have I got left" a list of accounts cannot say.
  if (report.note) blocks.push(element("p", "otk-note", report.note));
  showDocket("balance", "Balance", blocks);
}

export async function openInfo() {
  openSlip("info", "Info");
  const report = await api.info();
  /* The report's blocks, drawn as the slip draws them: the model's own
     name is the subject and takes the title, the story on the page is
     the closing block, and every other fact is a leader. Chosen by
     LABEL, not by position — and a label this does not know simply
     stays a leader, so a renamed row degrades to a line rather than to
     an empty screen. */
  const blocks = [];
  const closing = [];
  const facts = element("div", "otk-v otk-v--sm");
  let title = null;
  for (const section of report.sections) {
    if (section.note) blocks.push(element("p", "otk-note", section.note));
    for (const [label, value] of section.rows) {
      const name = label.toLowerCase();
      // The subject takes the title, the open story closes the slip,
      // and the premise is not a fact about the session — it has a tab
      // of its own, at reading measure, where it can be corrected.
      if (name === "model" && !title) title = value;
      else if (name === "system") continue;
      else if (name === "story") closing.push(element("span", "otk-docket__story", value));
      else if (name === "messages") closing.push(span("otk-index__sub", `${value} messages`));
      // The endpoint belongs UNDER the backend it addresses, not beside
      // it: it is long, and it is the same fact said more precisely.
      else if (name === "url") facts.append(span("otk-leader__aside otk-leader__aside--tight", value));
      else facts.append(leader(name, value));
    }
  }
  // The rule goes under the SUBJECT — what the slip is about — not
  // between two blocks of the same kind of fact.
  if (facts.childElementCount) blocks.push(element("div", "otk-hr"), facts);
  if (closing.length) blocks.push(element("div", "otk-rule--double"));
  if (closing.length) {
    const block = element("div", "otk-v otk-v--sm");
    block.append(span("otk-label", "on the page"), ...closing);
    blocks.push(block);
  }
  showDocket("info", "Info", blocks, "", title);
}

/* A value long enough to wrap is not a figure and cannot ride a leader:
   the dots would run into a paragraph. Past this many characters the row
   stacks instead — the name above, the value under it. */
const _FIGURE = 42;

function leader(label, value, kind = "") {
  const text = String(value);
  if (text.length <= _FIGURE) {
    const line = element("div", "otk-leader");
    line.append(span("", label), span(kind, text));
    return line;
  }
  const block = element("div", "otk-v otk-v--xs");
  block.append(span("otk-margin__key", label), element("p", `otk-derived ${kind}`.trim(), text));
  return block;
}

/** The slip up before its data — a click must answer NOW, and the modal
    keeps further clicks from queueing screens behind it. */
function openSlip(kind, title) {
  const popup = popups.get("/report");
  if (popup.open && popup.dataset.report === kind) return;
  showDocket(kind, title, []);
}

/* What each report is worth in BOX — the measure is the KIND's, decided
   here and not by whatever arrived: balance is a column of figures on a
   narrow slip, usage and info take the default width. Height is torn to
   what a slip says, except balance — its figures come off the network,
   one account at a time, and a box that is settled before they land is a
   box they can arrive into. */
const _SIZE = {
  balance: ["otk-docket--narrow", "otk-docket--fixed"],
  usage: [],
  info: [],
};
// A slip that cannot change size may open before it has anything to say.
const _settles = (kind) => (_SIZE[kind] ?? []).includes("otk-docket--fixed");
const _SIZES = [...new Set(Object.values(_SIZE).flat())];

function showDocket(kind, title, blocks, note = "", subject = "") {
  const popup = popups.get("/report");
  // One slip, three reports: the kind is on the popup so a screen can
  // tell them apart; what the slip SAYS is entirely the report's.
  popup.dataset.report = kind;
  const slip = $(".otk-docket", popup);
  slip.classList.remove(..._SIZES);
  slip.classList.add(...(_SIZE[kind] ?? []));
  $("[data-title]", popup).textContent = title;
  // A report with scopes fills this in after; one without shows none,
  // and never the last report's.
  const strip = $("[data-scopes]", popup);
  if (strip) {
    strip.replaceChildren();
    strip.hidden = true;
  }
  // The subject a report is ABOUT, where a slip prints one.
  const body = $("[data-report-body]", popup);
  body.replaceChildren(...(subject ? [element("span", "otk-docket__title", subject)] : []), ...blocks);
  // Nothing to say yet means the read is still out. A slip torn to its
  // content waits out of sight, because opening it empty would resize it
  // under the pointer when the answer lands; one with a settled box opens
  // straight away and the figures arrive into it.
  slip.classList.toggle("is-waiting", !blocks.length && !subject && !_settles(kind));
  // The foot carries what the report says about ITSELF — its scope, its
  // count — and nothing when it has nothing: a line naming the command
  // that opened the screen tells a reader what they just did.
  footnote(popup, note);
  if (!popup.open) popup.showModal();
  $(".otk-docket__body", popup).focus();
}
