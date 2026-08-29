/* Inside one story: the level-2 dossier — premise, messages, scenes and
   cast as four tabs of one panel, the way a case file is read.

   Scenes and cast are the same pane with the fields transposed: an
   index of one kind, a reading column at full measure, and the
   apparatus margin beside it holding everything the extractor wrote and
   nobody may edit. What IS editable opens where it is read.

   Any story opens whole, and any story EDITS: every write carries the
   story it belongs to, so a correction lands where it was read whether
   or not that story is the open one. The level above (the story
   browser) stays open UNDERNEATH this panel: leaving — the back button
   or Esc — reveals it exactly as it was left, and when there is none
   to reveal, the back button opens it positioned on this story.

   Every write goes out through `api.act` with the address the field
   itself carries (`kind`, `target`); the screen never invents one. A
   refusal is carried INTO the redraw as the footnote, because inside a
   popup the status line is behind a modal, and a refusal said there is
   a refusal nobody reads. */

import * as api from "./api.js";
import {
  ask,
  browser,
  closeAll,
  edited,
  editable,
  footnote,
  guard,
  popups,
  wiring,
} from "./browser.js";
import { $, $$, actionButton, element, pickFile, row, span } from "./dom.js";
import { ago, excerpt, label } from "./format.js";
import { typeset } from "./prose.js";
import { landed } from "./shell.js";

/* What a premise may be read from. A premise is prose somebody wrote —
   a story's opening terms — so the two shapes a person keeps prose in,
   and nothing else: a browser will offer anything, and a `.png` read as
   text is a screenful of noise where the premise was. */
const _PREMISE_FILES = ".txt,.md,.markdown,text/plain,text/markdown";

/** Open the dossier — on the open story by default, or on `story` (a
    row of the browser's). `tab` is where it opens; `answered` is what a
    write this screen triggered came back with; `allStories` is where
    the back button goes when no story browser waits underneath. */
export async function openStory({ story = null, tab = "messages", answered = "", allStories } = {}) {
  const popup = popups.get("/story");
  // The panel is up before its data: a click must answer NOW, and the
  // modal keeps further clicks from queueing screens behind it.
  $("[data-story-title]", popup).textContent = label(story?.label) || "Story";
  if (!popup.open) popup.showModal();

  const facts = await api.facts();
  const subject = story ?? { id: facts.story_id, label: facts.story || "" };
  const inside = subject.id === null || subject.id === facts.story_id;
  /* ONE read for all four tabs. Three would let an extraction pass land
     between two of them and hand this panel a torn story — scenes
     covering messages it was told nothing about. */
  const opened = subject.id === null ? null : await api.story(subject.id);

  $("[data-story-title]", popup).textContent = label(subject.label) || "(untitled)";
  const read = opened?.read_through ?? 0;
  $("[data-tabs-aside]", popup).textContent = [
    read ? `read through ${read}` : "",
    opened?.unread ? `${opened.unread} unread` : "",
  ]
    .filter(Boolean)
    .join(" · ");

  const view = {
    popup,
    subjectArg: story,
    subject,
    inside,
    facts,
    messages: opened?.messages ?? [],
    premise: opened?.premise ?? "",
    memory: opened && !opened.notice ? opened : null,
    refused: opened?.notice ?? "",
  };

  for (const button of $$(".otk-tab", popup)) {
    button.disabled = false;
    button.onclick = () => show(view, button.dataset.tab);
  }
  $("[data-back]", popup).onclick = () => {
    // The browser underneath was never closed: leaving reveals it as it
    // was left. Without one, the back button opens it — on this story.
    popup.close();
    if (!popups.get("/stories")?.open) allStories?.(subject.id);
  };
  show(view, tab);
  if (answered) footnote(popup, answered);
}

/** The landing every "continue here" goes through — exported because the
    level above (the story browser) lands the same way, at the tail. */
export async function land(storyId, messageId, action) {
  /* Resuming and setting aside MOVE the session's head; forking MAKES a
     story, so it is a creation on the story it copies. */
  const { notice } =
    action === "fork"
      ? await api.fork(storyId, messageId)
      : await api.setHead(storyId, messageId, action === "truncate");
  closeAll();
  await landed(notice, { redraw: "always" });
}

// ---------- the shell of the four tabs ----------

function show(view, tab, targetId = null) {
  for (const button of $$(".otk-tab", view.popup)) {
    button.setAttribute("aria-selected", String(button.dataset.tab === tab));
  }
  for (const pane of $$("[data-pane]", view.popup)) {
    pane.hidden = pane.dataset.pane !== tab;
  }
  const pane = $(`[data-pane="${tab}"]`, view.popup);
  if (tab === "messages") buildMessages(view, pane);
  else if (tab === "scenes") buildScenes(view, pane, targetId);
  else if (tab === "cast") buildCast(view, pane, targetId);
  else buildPremise(view, pane);
}

/** Reopen this dossier after a write, on the same tab, carrying what
    the write answered — the one way every save here comes back. */
function reopen(view, tab, notice) {
  return openStory({ story: view.subjectArg, tab, answered: notice });
}

// ---------- messages: index rail, one line a turn, a reader ----------

function buildMessages(view, pane) {
  sceneIndex(view, $("[data-index]", pane), null, {
    onPick: (scene) => show(view, "scenes", scene.id),
  });
  const rows = view.messages.map((message, i) => ({
    ...message,
    position: i + 1,
    last: i === view.messages.length - 1,
    haystack: `${message.body} ${message.speaker ?? ""}`.toLowerCase(),
  }));
  footnote(view.popup, `${rows.length} ${rows.length === 1 ? "message" : "messages"}`);
  if (!rows.length) $("[data-actions]", pane).replaceChildren();
  const edit = () => $("[data-detail] .otk-editable", pane)?.focus();
  browser(view.popup, {
    root: pane,
    rows,
    drawRow: (message) => {
      const who = message.role === "user" ? "you" : message.speaker || "—";
      const drawn = row(
        span("otk-row__id", String(message.position)),
        span(message.role === "user" ? "otk-row__who otk-row__who--you" : "otk-row__who", who),
        span("otk-row__title", excerpt(message.body, 300)),
      );
      if (message.kind && message.kind !== "dialogue") drawn.append(span("otk-tag", message.kind));
      return drawn;
    },
    drawPreview: (message) => drawReader(view, pane, message, edit),
    onOpen: (message) => resumeAt(view, message),
    onEdit: edit,
    empty: (filtered) =>
      filtered
        ? { line: "No turn matches that.", hint: `clear the filter to see all ${rows.length}` }
        : { line: "Nothing played yet.", hint: "continue this story to play into it" },
  });
}

function reader(text, save) {
  /* A played turn READS as it played — the model's dialogue and its
     `*emphasis*` typeset exactly as the transcript typesets them — and
     is still the field that corrects it. So the two are one box: the
     rendering rests there, and the field takes its place under the
     caret. They share the editable's box (no margin, no padding, no
     border, the same face) and the rendering keeps its newlines, so
     opening one moves nothing — which is the rule the whole editing
     ground is built on. */
  const box = element("div", "otk-editable otk-prose otk-prose--read otk-typeset");
  const field = editable("otk-prose otk-prose--read", { text, save });
  field.hidden = true;
  box.tabIndex = 0;

  const paint = () => {
    const { spoken, nodes } = typeset(field.value);
    box.classList.toggle("otk-prose--dialogue", spoken);
    box.replaceChildren(...nodes);
  };
  const open = () => {
    box.hidden = true;
    field.hidden = false;
    field.focus();
  };
  paint();
  box.addEventListener("focus", open);
  box.addEventListener("click", open);
  // `editable`'s own blur puts the stored text back, so by the time this
  // runs the value is what should be read again.
  field.addEventListener("blur", () => {
    paint();
    box.hidden = false;
    field.hidden = true;
  });
  const both = element("div", "otk-reader");
  both.append(box, field);
  return both;
}

function drawReader(view, pane, message, edit) {
  const head = element("div", "otk-detail__head");
  head.append(span("otk-label otk-label--ink", `Message ${message.position}`));
  if (message.kind) head.append(span("otk-tag", message.kind));

  // The message is corrected where it is read: the reader IS the field.
  const body = element("div", "otk-detail__section");
  body.append(edited(reader(message.body, (text) => saveMessage(view, message, text)), "message"));

  const out = [head, body];

  /* What the session recorded WITH the turn. The model is a fact and
     rides a fact row; the template is the TEXT the direction filled —
     prose, and prose wraps rather than running under its own label. */
  const recorded = [];
  if (message.provider || message.model) {
    recorded.push(fact("answered by", [message.provider, message.model].filter(Boolean).join(" · ")));
  }
  if (message.template) {
    recorded.push(derivedRow("template", "read only", element("p", "otk-derived", message.template)));
  }
  if (recorded.length) out.push(sectionOf("Recorded with the turn", recorded));

  // What the extractor writes onto it afterwards — present, or pending.
  if (message.role === "assistant") {
    out.push(
      sectionOf("Written by the extractor", [
        message.speaker
          ? derivedRow("speaker", "read only", element("p", "otk-derived", message.speaker))
          : derivedRow(
              "speaker",
              "pending",
              element("span", "otk-pending", "named on the next pass"),
            ),
      ]),
    );
  }

  // The verbs are pinned under the pane, not appended to the body: a
  // longer or shorter message must never move the button being aimed at.
  $("[data-actions]", pane).replaceChildren(
    actionButton("Resume here", {
      kind: "otk-btn--primary",
      onclick: guard(() => resumeAt(view, message)),
    }),
    actionButton("Edit", { onclick: () => edit() }),
    actionButton("Fork here", {
      onclick: guard(() => land(view.subject.id, message.id, "fork")),
    }),
  );
  return out;
}

async function saveMessage(view, message, text) {
  const { notice } = await api.editMessage(view.subject.id, message.id, text);
  await landed("", { redraw: "always" });
  reopen(view, "messages", notice);
}

function resumeAt(view, message) {
  // The last turn resumes as it stands; an earlier one has to say what
  // to do with everything after it.
  if (message.last) return land(view.subject.id, message.id, "resume");
  return askLanding(view, message);
}

async function askLanding(view, message) {
  /* Picking an earlier turn has to say what becomes of everything after
     it. The radios choose; the button applies — a click on "Set aside"
     must not set anything aside. */
  let chosen = "fork";
  const follow = view.messages.length - message.position;
  const choice = await ask("landing", (dialog) => {
    $("[data-title]", dialog).textContent = `Resume from message ${message.position}?`;
    $(".otk-dialog__body", dialog).textContent =
      `${follow === 1 ? "One turn follows" : `${follow} turns follow`} this one. ` +
      "Choose what happens to them.";
    const options = $$("[data-select]", dialog);
    const confirm = $('[data-choice="confirm"]', dialog);
    const select = (picked) => {
      chosen = picked.dataset.select;
      for (const option of options) {
        option.setAttribute("aria-checked", String(option === picked));
      }
      // The button must say what it will DO. A button reading "Fork"
      // that sets aside is the worst sentence this app could write.
      if (confirm) confirm.textContent = $(".otk-choice__name", picked)?.textContent ?? chosen;
    };
    for (const option of options) option.onclick = () => select(option);
    // Fork is the default: it is the one choice that loses nothing.
    const fork = options.find((option) => option.dataset.select === "fork");
    if (fork) select(fork);
  });
  if (choice === "confirm") land(view.subject.id, message.id, chosen);
}

// ---------- scenes: index, reading column, apparatus margin ----------

function buildScenes(view, pane, sceneId = null) {
  wiring(view.popup);
  const scenes = view.memory?.scenes ?? [];
  footnote(view.popup, `${scenes.length} ${scenes.length === 1 ? "scene" : "scenes"}`);
  const reading = $("[data-reading]", pane);
  const margin = $("[data-margin]", pane);
  const scene = scenes.find((entry) => entry.id === sceneId) ?? scenes[0];
  sceneIndex(view, $("[data-index]", pane), scene?.id ?? null, {
    onPick: (picked) => buildScenes(view, pane, picked.id),
  });
  if (!scene) {
    reading.replaceChildren(
      element(
        "p",
        "otk-note",
        view.refused ||
          "No scenes yet. The extractor reads played messages into scenes as the story grows.",
      ),
    );
    margin.replaceChildren();
    return;
  }

  reading.replaceChildren(
    span(
      "otk-label otk-label--accent",
      scene.span ? `Scene ${scene.number} · messages ${scene.span}` : `Scene ${scene.number}`,
    ),
    title(view, "scenes", scene.title, "(untitled scene)", (text) =>
      api.editScene(view.subject.id, scene.id, { title: text }),
    ),
    ...lede(view, "scenes", {
      text: scene.summary,
      empty: "(no summary yet)",
      name: "summary",
      save: (text) => api.editScene(view.subject.id, scene.id, { summary: text }),
    }),
    journalPassages(
      view,
      "scenes",
      scene.journals,
      (record) => named(view.memory?.characters, record.character, "name", "someone"),
      (name) => `${name} records`,
    ),
  );

  const facts = [];
  if (scene.present.length) facts.push(marginFact("present", presentLine(view, scene.present)));
  if (scene.updated_at) {
    facts.push(
      marginFact("extracted", element("p", "otk-margin__value otk-margin__value--mono", ago(scene.updated_at))),
    );
  }
  if (scene.history) {
    facts.push(
      marginBlock(
        "the arc through here",
        element("p", "otk-passage__body otk-prose--margin", scene.history),
      ),
    );
  }
  margin.replaceChildren(span("otk-label", "Apparatus"), ...facts, marginFoot());
}

function sceneIndex(view, rail, currentId, { onPick }) {
  const scenes = view.memory?.scenes ?? [];
  const head = element("div", "otk-index__head");
  head.append(span("otk-label", "Scenes"), span("otk-index__sub otk-push", String(scenes.length)));
  const list = element("div", "otk-index__list");
  for (const scene of scenes) {
    const item = element("button", "otk-index__item");
    item.type = "button";
    if (scene.id === currentId) item.setAttribute("aria-selected", "true");
    item.append(
      span("otk-index__title", scene.title || "(untitled scene)"),
      span("otk-index__sub", scene.span ? `msg ${scene.span}` : ""),
    );
    item.onclick = guard(() => onPick(scene));
    list.append(item);
  }
  // What the extractor has NOT read: a dashed row where the scene that
  // will cover it goes, so its absence has a place rather than being a
  // silence at the end of the list.
  if (view.memory?.unread) {
    const pending = element("div", "otk-index__item otk-index__item--pending");
    pending.append(
      span("otk-index__title otk-absent", "not read yet"),
      span("otk-index__sub", `msg ${view.memory.unread_span}`),
    );
    list.append(pending);
  }
  const parts = [head, list];
  if (!scenes.length && !view.memory?.unread) {
    parts.push(
      element(
        "p",
        "otk-note otk-index__note",
        view.refused || "The extractor reads played messages into scenes.",
      ),
    );
  }
  if (view.inside) parts.push(extractBlock(view));
  rail.replaceChildren(...parts);
}

function extractBlock(view) {
  /* The pass is a background job, so what it needs is a state and not
     only a button: how much is unread, and the one control that reads
     it now. It sits at the foot of the index because that is the column
     a pass fills. */
  const box = element("div", "otk-extract");
  const line = element("div", "otk-extract__line");
  const unread = view.memory?.unread ?? 0;
  line.append(
    element("span", unread ? "otk-dot otk-dot--off" : "otk-dot"),
    span("otk-extract__state", unread ? `${unread} unread` : "all read"),
  );
  const button = element("button", "otk-btn", "Extract now");
  button.type = "button";
  button.dataset.command = "/extract";
  box.append(line, button);
  return box;
}

// ---------- cast: the same pane with the fields transposed ----------

function buildCast(view, pane, characterId = null) {
  wiring(view.popup);
  const cast = view.memory?.characters ?? [];
  footnote(view.popup, `${cast.length} ${cast.length === 1 ? "character" : "characters"}`);
  const rail = $("[data-index]", pane);
  const reading = $("[data-reading]", pane);
  const margin = $("[data-margin]", pane);
  const character = cast.find((entry) => entry.id === characterId) ?? cast[0];

  const head = element("div", "otk-index__head");
  head.append(span("otk-label", "Cast"), span("otk-index__sub otk-push", String(cast.length)));
  const list = element("div", "otk-index__list");
  for (const entry of cast) {
    const item = element("button", "otk-index__item");
    item.type = "button";
    if (entry.id === (character?.id ?? null)) item.setAttribute("aria-selected", "true");
    item.append(
      span("otk-index__title", entry.name),
      span("otk-index__sub", inScenes(entry)),
    );
    item.onclick = guard(() => buildCast(view, pane, entry.id));
    list.append(item);
  }
  const parts = [head, list];
  if (view.inside) parts.push(extractBlock(view));
  rail.replaceChildren(...parts);

  if (!character) {
    reading.replaceChildren(
      element(
        "p",
        "otk-note",
        view.refused || "No characters yet. The extractor names the cast as the story grows.",
      ),
    );
    margin.replaceChildren();
    return;
  }

  reading.replaceChildren(
    span(
      "otk-label otk-label--accent",
      `Character · ${inScenes(character)}`,
    ),
    element("h3", "otk-reading__title", character.name),
    ...lede(view, "cast", {
      text: character.description,
      empty: "(no description yet)",
      name: "description",
      save: (text) => api.editCharacter(view.subject.id, character.id, { description: text }),
    }),
    journalPassages(
      view,
      "cast",
      character.journals,
      (record) => named(view.memory?.scenes, record.scene, "title", "a scene"),
      (name) => name,
    ),
  );

  const facts = [];
  // Where they stand: the newest state among their records, which is the
  // only one ever read again.
  const now = [...character.journals].reverse().find((record) => record.state)?.state;
  if (now) facts.push(marginFact("now", element("p", "otk-margin__value", now)));
  facts.push(
    marginFact(
      "aliases",
      element("p", "otk-derived", character.aliases.join(" · ") || "none recorded"),
      "read only",
    ),
  );
  facts.push(
    character.card
      ? marginFact("card", editable("otk-derived", {
          text: character.card,
          save: (text) => saveField(view, "cast", () =>
            api.editCharacter(view.subject.id, character.id, { card: text }),
          ),
        }))
      : marginFact(
          "card",
          element("p", "otk-derived", "none — extracted from the story, not imported"),
          "read only",
        ),
  );
  margin.replaceChildren(span("otk-label", "Apparatus"), ...facts, marginFoot());
}

// ---------- the field shapes both lenses share ----------

function title(view, tab, text, fallback, save) {
  /* The scene's own name, edited where it is READ — its heading. Not a
     row in the apparatus column: that column holds what the extractor
     writes, and a title a hand can correct does not belong in it. */
  const head = editable("otk-reading__title", {
    text,
    save: (edited) => saveField(view, tab, () => save(edited)),
  });
  head.placeholder = fallback;
  head.rows = 1;
  return head;
}

function lede(view, tab, { text, empty, name, save }) {
  /* The reading column's own text: the scene's summary, the character's
     description. It IS a field — same face, same rule under it, nothing
     to click open and nothing to move — and the line under it names what
     it holds, then says how to commit it once the caret is in. */
  if (!save) return [element("p", "otk-reading__lede", text || empty)];
  return [
    edited(
      editable("otk-reading__lede", {
        text,
        save: (edited) => saveField(view, tab, () => save(edited)),
      }),
      name,
    ),
  ];
}

function journalPassages(view, tab, journals, nameOf, rubricOf) {
  /* The journal read as the design reads it: one passage per record —
     the rubric names who (or which scene) records, the body is the
     entry, and the state rides under it as a note. The entry opens for
     correction where it is read; the state is the extractor's own line
     about a moment that has passed, and is not edited here.

     One record, read from either side: a scene draws its characters'
     lines, a character draws the scenes they were in, and both address
     the same journal id when a correction is saved. */
  const box = element("div", "otk-passages");
  for (const record of journals ?? []) {
    const passage = element("div", "otk-passage");
    passage.append(span("otk-passage__rubric", rubricOf(nameOf(record))));
    passage.append(
      edited(
        editable("otk-passage__body", {
          text: record.entry,
          save: (text) =>
            saveField(view, tab, () =>
              api.editJournal(view.subject.id, record.id, { entry: text }),
            ),
        }),
        "entry",
      ),
    );
    if (record.state) passage.append(element("p", "otk-note", record.state));
    box.append(passage);
  }
  return box;
}

/** The name of the row on the OTHER side of a journal record — the
    character a scene's entry was written by, the scene a character's
    entry was written in. */
function named(rows, id, key, fallback) {
  return (rows ?? []).find((row) => row.id === id)?.[key] || fallback;
}

/** How much of the story a character is in, counted from their own
    records rather than sent as a figure of its own. */
function inScenes(character) {
  const scenes = new Set(character.journals.map((record) => record.scene)).size;
  return `in ${scenes} ${scenes === 1 ? "scene" : "scenes"}`;
}

async function saveField(view, tab, write) {
  /* One correction, wherever it was made. WHICH row it addresses is the
     caller's — a scene, a character, a journal record each have their
     own door — and what is shared is only what happens after: the answer
     is carried INTO the redraw, because a screen that rebuilds on the
     write would otherwise put its standing footnote back over it. */
  const { notice } = await write();
  reopen(view, tab, notice);
}

function presentLine(view, present) {
  /* Who was in the scene, each name a door to that character — the
     journal is the same entry from the other side. */
  const line = element("p", "otk-margin__value");
  present.forEach((name, i) => {
    if (i) line.append(", ");
    const character = (view.memory?.characters ?? []).find((entry) => entry.name === name);
    if (!character) {
      line.append(name);
      return;
    }
    const link = element("a", "", name);
    link.href = "#";
    link.onclick = guard((event) => {
      event.preventDefault();
      show(view, "cast", character.id);
    });
    line.append(link);
  });
  return line;
}

function marginFact(key, valueNode, flag = "") {
  const box = element("div", "otk-margin__fact");
  const name = span("otk-margin__key", key);
  if (flag) name.append(span("otk-derived__flag", flag));
  box.append(name, valueNode);
  return box;
}

function marginBlock(key, valueNode) {
  const box = marginFact(key, valueNode);
  box.classList.add("otk-margin__block");
  return box;
}

function marginFoot() {
  return element(
    "p",
    "otk-note otk-note--push",
    "Nothing in this column is rewritten by hand — the extractor writes it on every pass.",
  );
}

function derivedRow(key, flag, valueNode) {
  const box = element("div", "otk-field-row");
  const name = span("otk-margin__key", key);
  name.append(span("otk-derived__flag", flag));
  box.append(name, valueNode);
  return box;
}

// ---------- premise: one long text, and the two ways it gets there ----------

function buildPremise(view, pane) {
  wiring(view.popup);
  footnote(view.popup, "sent as the system message");
  const box = $(".otk-premise__body", pane);
  const state = $("[data-premise-state]", pane);
  const save = $("[data-save-system]", pane);
  const read = $("[data-import-system]", pane);
  box.value = view.premise;
  /* Nothing to save until something changed: the button is a door that
     does something, and a door that does nothing should not look like
     one. The sentence beside it says why it is open. */
  const settle = () => {
    const changed = box.value !== view.premise;
    save.setAttribute("aria-disabled", String(!changed));
    if (!state.textContent || state.textContent === "Unsaved changes") {
      state.textContent = changed ? "Unsaved changes" : "";
    }
  };
  settle();
  box.oninput = settle;
  read.onclick = guard(async () => {
    /* The file is read HERE and its text put in the box: what is saved
       is what the reader can see and correct, and a path over HTTP
       would name a file on the machine otaku runs on, which is not the
       one the file was picked from. */
    const picked = await pickFile(_PREMISE_FILES);
    if (!picked) return;
    box.value = await picked.text();
    state.textContent = `Read ${picked.name}. Save to keep it.`;
    save.setAttribute("aria-disabled", "false");
  });
  save.onclick = guard(async () => {
    if (save.getAttribute("aria-disabled") === "true") return;
    /* A premise written before the first message is how a reader sets
       the scene, so it must land — and a premise lives ON a story, which
       means there has to be one to put it on. The terminal reaches the
       same place from the other side (`session._ensure_story`); here the
       story is made first, and the view KEEPS it: a second save must
       correct the premise it just wrote, not start another story. */
    if (view.subject.id === null) view.subject.id = (await api.newStory()).story;
    const { notice } = await api.setPremise(view.subject.id, box.value);
    await landed("");
    view.premise = box.value;
    state.textContent = "";
    settle();
    footnote(view.popup, notice);
  });
}

// ---------- small shared shapes ----------

function sectionOf(label, children) {
  const box = element("section", "otk-detail__section");
  box.append(span("otk-label", label), ...children);
  return box;
}

function fact(key, value) {
  const line = element("p", "otk-fact");
  line.append(span("", key), span("", value));
  return line;
}
