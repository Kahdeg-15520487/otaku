/* The premise editor: one long text, and the two ways it gets there —
   typed, or read out of a file the reader picks. The FILE never leaves
   this machine's browser: what is sent is what ends up in the box. */

import * as api from "./api.js";
import { closeAll, guard, hint, popups } from "./browser.js";
import { $, pickFile } from "./dom.js";
import { landed } from "./shell.js";

/* What a system prompt may be read from. A premise is prose somebody
   wrote — a story's opening terms — so the two shapes a person keeps
   prose in, and nothing else: a browser will offer anything, and a
   `.png` read as text is a screenful of noise where the premise was. */
const _PREMISE_FILES = ".txt,.md,.markdown,text/plain,text/markdown";

export async function openSystem(answered = "") {
  const popup = popups.get("/system");
  const box = $(".otk-system", popup);
  const facts = await api.facts();
  box.value = facts.system ?? "";
  // The same slot the other panels use, saying the same kind of thing:
  // what this screen IS. A story's title is content, not chrome, and it
  // is already in the header behind this.
  hint(popup, answered || "/system command");

  $("[data-import-system]", popup).onclick = guard(async () => {
    /* The file is read HERE and its text put in the box: what is saved
       is what the reader can see and correct, and a path over HTTP
       would name a file on the machine otaku runs on, which is not the
       one the file was picked from. */
    const picked = await pickFile(_PREMISE_FILES);
    if (!picked) return;
    box.value = await picked.text();
    hint(popup, `Read ${picked.name}. Set to keep it.`);
  });
  $("[data-save-system]", popup).onclick = guard(async () => {
    const { notice } = await api.act("set-system", { text: box.value });
    closeAll();
    await landed(notice);
  });
  // The box is what this screen is: it opens on it, not on the buttons.
  box.setAttribute("autofocus", "");
  popup.showModal();
  box.focus();
  // At the beginning of it: focusing a textarea puts the caret at the
  // end, which opens a long premise on its last line.
  box.setSelectionRange(0, 0);
  box.scrollTop = 0;
}
