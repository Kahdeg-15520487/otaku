/* The story browser: every story, the drill-in to one story's messages,
   and the landings — TEMPLATE 1 of the design, over `browser()`.

   A screen fetches what it shows as it opens: a popup drawing
   yesterday's numbers is worse than none. Every write goes out through
   `api.act` and comes back through `landed`, so no screen decides what
   a sentence means or when the flow is redrawn. The ask dialogs it
   opens (rename, delete, the landing choice) are filled here, because
   what a landing does to the story on screen is this screen's to say. */

import * as api from "./api.js";
import { ask, browser, closeAll, footnote, guard, hint, inlineEditor, popups } from "./browser.js";
import { $, $$, element, row, span } from "./dom.js";
import { ago, excerpt, stamp, when } from "./format.js";
import { landed } from "./shell.js";

export async function openStories(answered = "") {
  const popup = popups.get("/stories");
  // No haystack on these rows: the filter is `api.search`, whole — the
  // union of buried content and the row's face is the backend's.
  const rows = await api.stories();
  // A drill-in takes the header and the footer over; opening the list
  // puts both back.
  crumb(popup, "");
  // The drill-in gives the list two thirds of the panel; the list of
  // stories wants the preview beside it just as wide.
  $(".otk-browser", popup).classList.remove("otk-browser--wide-list");
  footnote(popup, answered || `${rows.length} ${rows.length === 1 ? "story" : "stories"}`);
  hint(popup, "↑/↓ navigate · / filter");
  browser(popup, {
    rows,
    drawRow: (story) =>
      row(
        span("otk-row__num", stamp(story.updated_at)),
        span("otk-row__num", "·"),
        span("otk-row__num otk-row__num--count", String(story.messages)),
        span("otk-row__num", "msg"),
        span("otk-row__num", "·"),
        span("otk-row__text", story.label || "(untitled)"),
      ),
    drawPreview: (story) =>
      [
        element("p", "otk-preview__eyebrow", story.model || "no model"),
        element("h3", "otk-preview__title", story.label || "(untitled)"),
        element(
          "p",
          "otk-meta",
          `${when(story.updated_at)} · ${ago(story.updated_at)} · ` +
            `${story.messages} ${story.messages === 1 ? "message" : "messages"}`,
        ),
        story.story_so_far && element("p", "otk-preview__body", story.story_so_far),
        previewSection(
          "First prompt",
          element("p", "otk-preview__body", story.first_user || "(nothing played yet)"),
        ),
        actions(
          // A story with nothing played in it has no message to land on,
          // so the two verbs that land are off — and the three that do
          // not (its messages, its name, its life) stay on.
          action("Continue", {
            kind: "otk-btn--primary",
            opens: true,
            off: !story.messages,
            act: () => landOn(story, "resume"),
          }),
          action("Messages", { act: () => openStoryMessages(story) }),
          action("Rename", { act: () => renameStory(story) }),
          action("Fork", { off: !story.messages, act: () => landOn(story, "fork") }),
          action("Delete", { kind: "otk-btn--danger", act: () => confirmDelete(story) }),
        ),
      ].filter(Boolean),
    onOpen: (story) => (story.messages ? landOn(story, "resume") : undefined),
    onDelete: confirmDelete,
    search: api.search,
  });
  popup.showModal();
}

async function openStoryMessages(story, answered = "") {
  const popup = popups.get("/stories");
  const messages = await api.storyMessages(story.id);
  const rows = messages.map((message, i) => ({
    ...message,
    position: i + 1,
    last: i === messages.length - 1,
    haystack: message.body.toLowerCase(),
  }));
  crumb(popup, story.label || "(untitled)");
  // A message row is a line of the story and the preview is one message:
  // the list is what is read here, so it takes two thirds.
  $(".otk-browser", popup).classList.add("otk-browser--wide-list");
  footnote(popup, answered || `${rows.length} ${rows.length === 1 ? "message" : "messages"}`);
  hint(popup, "↑/↓ navigate · / filter");
  const edit = (message) => editMessage(popup, message, story);
  browser(popup, {
    rows,
    drawRow: (message) =>
      row(
        span("otk-row__num otk-row__num--count", String(message.position)),
        span("otk-row__num", "·"),
        span("otk-row__num otk-row__num--role", message.role),
        span("otk-row__num", "·"),
        // The list is two thirds of the panel here; a row shows as much
        // as fits and cuts the rest off with an ellipsis, never wrapping.
        span("otk-row__text", excerpt(message.body, 500)),
      ),
    drawPreview: (message) => {
      const body = element("p", "otk-preview__body is-editable", message.body);
      // The button below, and the same door for a click on the text
      // itself: the message is corrected where it is read.
      body.onclick = guard(() => edit(message));
      return [
        element("p", "otk-meta", `${message.role} · message ${message.position}`),
        body,
        // Three plain verbs and no primary among them: a message browser
        // is opened to fix a line as often as to continue from one.
        actions(
          action("Edit", { act: () => edit(message) }),
          action("Resume here", { opens: true, act: () => resumeAt(story, message) }),
          action("Fork here", { act: () => land(story.id, message.id, "fork") }),
        ),
      ];
    },
    onOpen: (message) => resumeAt(story, message),
    onEdit: edit,
    onBack: openStories,
  });
}

// ---------- what the highlighted row can be done to ----------

function actions(...buttons) {
  /* What the highlighted item can be done to, drawn under the item
     itself rather than in the header: the verbs that act on ONE thing
     belong beside the thing, and the header keeps only what acts on the
     whole list. */
  const box = element("div", "otk-actions");
  box.append(...buttons);
  return box;
}

function action(label, { kind = "", off = false, opens = false, act }) {
  const button = element("button", kind ? `otk-btn ${kind}` : "otk-btn", label);
  button.type = "button";
  button.disabled = off;
  // The row's own Enter, as a button: one door, marked so a reader of
  // the markup can see which of these the key does.
  if (opens) button.dataset.openRow = "";
  button.onclick = guard(act);
  return button;
}

function previewSection(label, ...blocks) {
  /* A titled block under a rule — the design's own section shape, which
     is where the rule between a summary and its first prompt comes
     from. */
  const section = element("section", "otk-preview__section");
  section.append(element("h4", "otk-label", label), ...blocks);
  return section;
}

// ---------- the landings ----------

async function landOn(story, action) {
  /* Continuing a story and forking one are the same landing the drill-in
     performs, at the story's LAST message — which is where the reader
     left it. The chain is read here rather than carried on the row: a
     list that knew every story's last message would have read every
     story's chain to draw itself. */
  const messages = await api.storyMessages(story.id);
  const last = messages.at(-1);
  if (!last) return;
  await land(story.id, last.id, action);
}

function resumeAt(story, message) {
  // The last turn resumes as it stands; an earlier one has to say what
  // to do with everything after it.
  return message.last ? land(story.id, message.id, "resume") : askLanding(story, message);
}

async function askLanding(story, message) {
  /* Picking an earlier turn has to say what becomes of everything after
     it. The radios choose; the button applies — a click on "Truncate"
     must not truncate. */
  let chosen = "fork";
  const choice = await ask("landing", (dialog) => {
    $("[data-title]", dialog).textContent = `Resume at message ${message.position}`;
    $(".otk-dialog__body", dialog).textContent =
      "There are messages after this one. Continuing here has to do something with them.";
    const options = $$("[data-select]", dialog);
    const confirm = $('[data-choice="confirm"]', dialog);
    const select = (picked) => {
      chosen = picked.dataset.select;
      for (const option of options) {
        const active = option === picked;
        option.classList.toggle("is-selected", active);
        option.setAttribute("aria-checked", String(active));
      }
      // The button must say what it will DO. A button reading "Fork"
      // that truncates is the worst sentence this app could write.
      if (confirm) confirm.textContent = $(".otk-choice__name", picked)?.textContent ?? chosen;
    };
    for (const option of options) option.onclick = () => select(option);
    // Fork is the default: it is the one choice that loses nothing.
    const fork = options.find((option) => option.dataset.select === "fork");
    if (fork) select(fork);
  });
  if (choice === "confirm") land(story.id, message.id, chosen);
}

async function land(storyId, messageId, action) {
  const { notice } = await api.act("land", { story: storyId, message: messageId, action });
  closeAll();
  await landed(notice, { redraw: "always" });
}

// ---------- the writes ----------

function editMessage(popup, message, story) {
  const body = $(".otk-preview__body", popup);
  if (!body) return;
  inlineEditor(body, {
    text: message.body,
    caption: `editing message ${message.position}`,
    save: async (text) => {
      const { notice } = await api.act("edit-message", { message: message.id, text });
      await landed("", { redraw: "always" });
      openStoryMessages(story, notice);
    },
  });
}

async function renameStory(story) {
  /* A story is titled where it is read — any story, not only the open
     one. The field opens with the title it has, because a rename is
     usually a correction; an empty one is refused by the backend, whose
     sentence says so. */
  if (!story) return;
  const dialog = $('dialog[data-dialog="rename"]');
  const field = $("input", dialog);
  const choice = await ask("rename", () => {
    $(".otk-dialog__body", dialog).textContent = `Renaming: ${story.label || "(untitled)"}`;
    field.value = story.label || "";
  });
  if (choice !== "rename") return;
  const { notice } = await api.act("rename-story", { story: story.id, title: field.value });
  // The header carries the open story's title, and this may be it.
  await landed("");
  openStories(notice);
}

async function confirmDelete(story) {
  const choice = await ask("delete-story", (dialog) => {
    $(".otk-dialog__name", dialog).textContent = story.label || "(untitled)";
    // The two facts that let a reader catch a wrong selection, in the
    // one operation that cannot be undone — from THIS story, never the
    // template's.
    $(".otk-dialog__subject .otk-meta", dialog).textContent =
      `${story.messages} messages · last played ${ago(story.updated_at)}`;
    $(".otk-dialog__body", dialog).textContent = "Its messages, scenes, and cast go with it.";
  });
  if (choice !== "delete") return;
  const { notice } = await api.act("delete-story", { story: story.id });
  await landed(notice, { redraw: "always" });
  openStories();
}

// ---------- the drill-in header ----------

function crumb(popup, title) {
  /* The header's drill-in half: one label holding the way back and the
     name of what was drilled into. Over the list the button IS the
     panel's own name and leads nowhere, so it is disabled — the same
     element in both states, so the header does not reflow on drill-in. */
  const back = $("[data-title]", popup);
  const trail = $("[data-crumb]", popup);
  if (!back || !trail) return;
  back.disabled = !title;
  back.onclick = title ? guard(() => openStories()) : null;
  trail.textContent = title ? ` / ${title}` : "";
  trail.hidden = !title;
  // What the list filters and what a drill-in filters are not the same
  // thing, and neither is what its buttons do.
  const filter = $(".otk-filter", popup);
  if (filter) filter.placeholder = title ? "filter messages" : "filter titles, arcs, message text";
  for (const button of $$("[data-list-only]", popup)) button.hidden = Boolean(title);
}
