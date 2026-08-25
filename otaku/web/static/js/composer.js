/* The input: what a submitted line becomes, and the menu that offers
   the commands while one is being typed.

   `submit` is the one door — Enter and the Send button both call it, so
   the button never has to synthesize a keystroke to reach the logic. */

import * as api from "./api.js";
import { midReply, playLine, run } from "./commands.js";
import { $, element, setValue, span } from "./dom.js";
import { allSpecs, isCommand } from "./table.js";
import { stopPlaying, tell } from "./transcript.js";

const composer = $(".otk-composer__input");
const menu = $(".otk-completions");

let offered = [];
let picked = 0;

/* What has been sent from this box, newest last, and where the reader
   is in it. `at === null` means "not walking" — the arrows only walk
   when there is nothing half-typed to lose, so a multi-line message
   keeps its own caret movement.

   The lines are the STORE's — the same history the terminal prompt
   walks: primed from it at boot, and every submission recorded back,
   so a reload (or a session in the other frontend) starts with the
   history it left. */
const history = [];
let at = null;

/** The store's recent lines, most recent first — called at every boot,
    because a restarted otaku may have played elsewhere since. */
export function primeHistory(lines) {
  history.length = 0;
  history.push(...[...lines].reverse());
  at = null;
}

/** One submitted line, wherever it came from. */
export function submit(line) {
  const said = line.trim();
  // A line typed during a reply is refused the way every other door
  // refuses it — silence here trains the reader to press Enter twice.
  if (!said || midReply()) return;
  if (history.at(-1) !== said) history.push(said);
  // Into the store's history too (blanks and immediate repeats are the
  // session's to skip) — fire-and-forget: the submission itself is the
  // event, and a lost record must not delay or fail it.
  api.act("record-history", { line: said }).catch(() => {});
  at = null;
  setValue(composer, "");
  hideMenu();
  if (isCommand(said)) run(said);
  else playLine(said);
}

export function wire() {
  composer.addEventListener("input", () => {
    // A line about the last attempt is over the moment the next one is
    // being typed.
    tell("");
    updateMenu();
  });
  composer.addEventListener("blur", hideMenu);
  composer.addEventListener("keydown", onKey);
  $(".otk-composer [data-send]")?.addEventListener("click", () => submit(composer.value));
  // The same place, the other half of the turn: what the model is doing
  // is stopped where it was asked for.
  $(".otk-composer [data-stop]")?.addEventListener("click", stopPlaying);
}

function onKey(event) {
  // While the menu is up it owns Enter and the arrows.
  if (!menu.hidden && offered.length) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      picked = (picked + (event.key === "ArrowDown" ? 1 : offered.length - 1)) % offered.length;
      updateMenu();
      return;
    }
    /* Enter takes the highlighted row unless the line already IS that
       row — a fully typed `/help` sends rather than re-completing. An
       inline word never claims Enter: the reader is mid-sentence, and
       Enter there is how the sentence is sent. */
    const typed = composer.value.trim();
    const settled = offered[picked]?.token.replace(_INLINE, "") === typed;
    if (event.key === "Tab" || (event.key === "Enter" && !settled && typed.startsWith("/"))) {
      event.preventDefault();
      accept(offered[picked]);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      hideMenu();
      return;
    }
  }
  if (event.key === "Escape") {
    setValue(composer, "");
    at = null;
    return;
  }
  if ((event.key === "ArrowUp" || event.key === "ArrowDown") && _walkable()) {
    event.preventDefault();
    _walk(event.key === "ArrowUp" ? -1 : 1);
    return;
  }
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    submit(composer.value);
  }
}

// ---------- what was sent before ----------

function _walkable() {
  /* Only with nothing to lose: an empty box, or a line this walk put
     there. Anything the reader typed keeps the arrows for its caret. */
  if (!history.length) return false;
  return !composer.value.trim() || (at !== null && composer.value === history[at]);
}

function _walk(step) {
  // Down from a box nobody is walking has nothing to go forward TO.
  if (at === null && step > 0) return;
  const next = at === null ? history.length - 1 : at + step;
  if (next < 0) {
    at = 0;
  } else if (next >= history.length) {
    // Past the newest is the empty box the reader started from.
    at = null;
    setValue(composer, "");
    return;
  } else {
    at = next;
  }
  setValue(composer, history[at]);
  composer.setSelectionRange(composer.value.length, composer.value.length);
}

// ---------- the completion menu ----------

/* The menu offers what the caret can take: a COMMAND while the line is
   nothing but its slash word, and the INLINE words — `/ooc`, `/cue` —
   while the slash is inside a prompt somebody is writing. The rows come
   from the shared table either way, so a new command appears here by
   existing; the `… ` prefix is how the table marks the inline half, and
   what a reader types is the bare word after it. */

const _INLINE = "… ";

function typing() {
  /* The slash word the caret is in, and whether it opens the line. "" if
     the caret is not in one — the menu has nothing to offer then. */
  const before = composer.value.slice(0, composer.selectionStart ?? composer.value.length);
  const word = before.split(/\s/).pop() ?? "";
  if (!word.startsWith("/")) return { word: "", opens: false };
  return { word, opens: before.trimStart() === word && !composer.value.includes("\n") };
}

function updateMenu() {
  const { word, opens } = typing();
  const was = offered.map((spec) => spec.token).join(" ");
  offered = !word
    ? []
    : allSpecs().filter((spec) => {
        const inline = spec.token.startsWith(_INLINE);
        if (opens === inline) return false;
        return (inline ? spec.token.slice(_INLINE.length) : spec.token).startsWith(word);
      });
  // A different set of rows is a different question: keeping the old
  // position would preselect a command nobody navigated to, and Enter
  // would take it.
  if (offered.map((spec) => spec.token).join(" ") !== was) picked = 0;
  picked = Math.min(picked, Math.max(0, offered.length - 1));
  menu.hidden = offered.length === 0;
  // Which half is on offer: the inline words are three characters and an
  // argument, and a column cut for `/set parameter <name> <val>` would
  // leave them stranded a third of the way across the row.
  menu.dataset.of = opens ? "commands" : "inline";
  menu.replaceChildren(
    ...offered.map((spec, i) => {
      const option = element("button", "otk-completions__row");
      option.type = "button";
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", String(i === picked));
      option.classList.toggle("is-selected", i === picked);
      // Token and argument shape are ONE label, as the help sheet writes
      // them: what you type, then what it takes.
      const label = span("otk-completions__label", "");
      // Mid-prompt the whole menu is inline words, so the table's `… `
      // prefix — which is there to tell `/ooc` the command from `/ooc`
      // the aside — has nothing left to distinguish.
      label.append(span("otk-completions__token", spec.token.replace(_INLINE, "")));
      if (spec.args) label.append(" ", span("otk-completions__args", spec.args));
      option.append(label, span("otk-completions__desc", spec.description));
      // The list is scrollable, so the row the arrows are on has to be
      // brought to where the reader is looking.
      if (i === picked) queueMicrotask(() => option.scrollIntoView({ block: "nearest" }));
      option.onmousedown = (event) => {
        event.preventDefault();
        accept(spec);
      };
      return option;
    }),
  );
}

function accept(spec) {
  /* A row that takes an argument is chosen to be given one, so the space
     comes with it; a bare command is ready to send as it stands. An
     INLINE word replaces the slash word the caret is in and leaves the
     prompt around it alone — that is the whole point of offering it
     mid-line. */
  const token = spec.token.startsWith(_INLINE) ? spec.token.slice(_INLINE.length) : spec.token;
  const taken = spec.args ? `${token} ` : token;
  const caret = composer.selectionStart ?? composer.value.length;
  const before = composer.value.slice(0, caret);
  const opened = before.length - (before.split(/\s/).pop() ?? "").length;
  setValue(composer, composer.value.slice(0, opened) + taken + composer.value.slice(caret));
  composer.focus();
  composer.setSelectionRange(opened + taken.length, opened + taken.length);
  updateMenu();
}

function hideMenu() {
  menu.hidden = true;
}
