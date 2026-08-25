/* The transfer screens: a card in, a story in, a story out.

   TEMPLATE 5 of the design — the drop-zone dialog and the persona ask —
   plus the two flows that need no dialog of their own. It lives beside
   `help.js` for the same reason: one screen, one module, and
   `commands.js` is the table that routes to them, not the place they
   are built.

   A path over HTTP would name a file on the SERVER, so nothing here
   sends one: an import sends what the browser read, a card sends its
   bytes, and an export is saved by the browser where the reader says. */

import * as api from "./api.js";
import { $, element, pickFile } from "./dom.js";
import { ask, guard } from "./browser.js";
import { landed, watchExtraction } from "./shell.js";
import { tell } from "./transcript.js";

export async function importDocument() {
  const file = await pickFile(".md,.jsonl,.txt");
  if (!file) return;
  const answer = await api.act("import", { text: await file.text(), name: file.name });
  await landed(answer.notice, { redraw: "always" });
  // The memoryless shapes build their memory now, through the same
  // forced pass a manual close runs. A native export arrives with its
  // memory and starts none — polling for a report it will never file
  // would run for the life of the tab.
  if (answer.watching) watchExtraction();
}

function cardName(argument) {
  /* The table declares `/card FILE [NAME]`, but a path over HTTP would
     name a file on the SERVER — the picker supplies the file, so what
     is left for the argument to be is the character's name. A reader
     following the table may still type a file; a token that looks like
     one is dropped rather than becoming the name, and the `@` sigil is
     stripped as every handler must strip it. */
  const words = argument.trim().replace(/^@/, "").split(/\s+/).filter(Boolean);
  if (words.length && /[./\\]/.test(words[0])) words.shift();
  return words.join(" ");
}

export async function importCard(argument = "") {
  /* The card dialog: choose a file, read what the import WILL do, and
     only then commit. The outcomes are the backend's own sentences
     about this card — the dialog decides where they appear, never what
     they say. */
  let data = "";
  let chosen = null;
  let prepared = null;
  let renamed = "";

  const choice = await ask("card", (dialog) => {
    const zone = $(".otk-dropzone", dialog);
    const picker = $("input[type=file]", dialog);
    const name = $("#otk-card-name", dialog);
    const filename = $("[data-file]", dialog);
    const outcomes = $("[data-outcomes]", dialog);
    const heading = $("[data-outcomes-label]", dialog);
    const note = $("[data-card-note]", dialog);
    const joins = $("[data-joins]", dialog);
    name.value = cardName(argument);
    filename.hidden = true;
    outcomes.hidden = true;
    heading.hidden = true;
    note.hidden = true;
    zone.classList.remove("is-filled", "is-dragover");
    // Which story it joins is the one fact this dialog cannot leave out:
    // a card lands in the OPEN story, not in a library.
    const story = $('[data-fact="story"]')?.textContent ?? "";
    joins.textContent = story ? `joins ${story}` : "";

    const take = async (file) => {
      if (!file) return;
      chosen = file;
      data = await encode(file);
      filename.textContent = file.name;
      filename.hidden = false;
      zone.classList.add("is-filled");
      zone.classList.remove("is-dragover");
      prepared = await api.act("prepare-card", {
        data,
        name: file.name,
        rename: (renamed = name.value.trim()),
      });
      if (!prepared.card) {
        note.textContent = prepared.notice;
        note.hidden = false;
        return;
      }
      // What an import always does (the three halves of the product's
      // own rule), and under them what the BACKEND said about this
      // particular card — its own sentences, unchanged.
      outcomes.replaceChildren(
        outcome("send the card's text as your next message, so it is a normal prompt"),
        outcome(`add ${prepared.card.name} to the cast of this story`),
        outcome("play the card's greeting as their first message"),
      );
      outcomes.hidden = false;
      heading.hidden = false;
      const caveats = [...prepared.card.notes];
      // A card that rides every request is worth saying out loud before
      // it is imported, not after.
      if (prepared.card.large) {
        caveats.push(`This card is about ${prepared.card.tokens} tokens, and rides every request.`);
      }
      note.textContent = caveats.join(" ");
      note.hidden = !caveats.length;
    };

    picker.onchange = guard(() => take(picker.files[0]));
    zone.ondragover = (event) => {
      event.preventDefault();
      zone.classList.add("is-dragover");
    };
    zone.ondragleave = () => zone.classList.remove("is-dragover");
    zone.ondrop = guard((event) => {
      event.preventDefault();
      return take(event.dataTransfer.files[0]);
    });
  });

  if (choice !== "import" || !chosen) return;
  const wanted = $("#otk-card-name")?.value.trim() ?? "";
  // The name may have been typed after the card was read: the prepared
  // one is bound to the name it was prepared with, so a changed name
  // means preparing again.
  if (!prepared?.card || wanted !== renamed) {
    prepared = await api.act("prepare-card", { data, name: chosen.name, rename: wanted });
  }
  if (!prepared.card) {
    tell(prepared.notice, "otk-error");
    return;
  }
  await askPersona(prepared.card, prepared.token);
}

function outcome(sentence) {
  const box = element("div", "otk-outcome");
  box.append(element("p", "", sentence));
  return box;
}

async function encode(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

async function askPersona(card, token) {
  /* The one question a card import asks: who its {{user}} is. The
     story's own memory of that is the default, so a story is asked once
     and later imports follow it. */
  let field = null;
  const choice = await ask("persona", (dialog) => {
    $("[data-title]", dialog).textContent = `Who is ${card.name} talking to?`;
    const body = $(".otk-dialog__body", dialog);
    body.replaceChildren(
      "The card writes to ",
      element("span", "otk-code", "{{user}}"),
      ". Whatever you put here replaces it.",
    );
    field = $("input", dialog);
    if (field) field.value = card.persona || "you";
    // The note is true only when there IS something remembered.
    const note = $("[data-remembered]", dialog);
    if (note) note.hidden = !card.persona;
  });
  if (choice !== "use") return;
  const { notice } = await api.act("add-card", {
    token,
    persona: field ? field.value.trim() : "you",
  });
  await landed(notice, { redraw: "always" });
}

export async function exportStory(argument = "") {
  const answer = await api.exportDocument();
  if (!answer.text) {
    // Whatever it refused with, in its own words.
    tell(answer.notice, "otk-error");
    return;
  }
  /* The table declares `/export [FILE]`: a typed name becomes the
     download's filename — the `@` sigil stripped as every handler
     strips it, and the document's suffix supplied when the name
     carries none (the backend's own rule; `.md` is
     `backend.api.transfer.EXPORT_SUFFIX`, which a page cannot import).
     Bare `/export` keeps the name the backend composed. */
  let named = argument.trim().replace(/^@/, "");
  if (named && !/\.[^./\\]+$/.test(named)) named += ".md";
  const filename = named || answer.name;
  const url = URL.createObjectURL(new Blob([answer.text], { type: "text/markdown" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  // Connected before the click and revoked after the turn of the event
  // loop: a detached link is ignored by some browsers, and revoking in
  // the same tick cancels a download that has not started.
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
  tell(`Exported ${filename}.`);
}
