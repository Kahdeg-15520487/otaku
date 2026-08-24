/* The shapes every screen is built from: the list-and-preview browser,
   the editors that open where the text already is, and the ask dialogs.

   The browser takes its rows and its drawing callbacks and owns nothing
   else — the terminal needed a base class with hooks for the same job,
   and a page does not. A grouped list (the model picker) hands in
   `groupOf`/`drawGroup` and the captions are drawn between the rows
   without ever being rows: the cursor walks `.otk-row` alone. */

import { $, $$, autosize, element, span } from "./dom.js";
import { tell } from "./transcript.js";

/* Every popup in the markup, by the command that opens it, and the two
   slots of its footer. They live here because a screen module must not
   have to import chrome from a sibling screen module — `browser.js` is
   what a screen is built FROM. */
export const popups = new Map($$("dialog[data-popup]").map((d) => [d.dataset.popup, d]));

export function closeAll() {
  for (const dialog of $$("dialog[open]")) dialog.close();
}

export function footnote(popup, text) {
  /* The footer's right-hand slot: the panel's own standing fact, set
     every time a screen opens — and what a WRITE answered with, carried
     into the redraw the write triggers, or the standing fact would go
     back over the answer milliseconds after it appeared. Says whether
     there was a slot at all: a popup without a footer is a real shape
     (the ask dialogs), and its notices go to the flow instead. */
  const slot = $$(".otk-popup__foot span", popup).at(-1);
  if (slot) slot.textContent = text;
  return Boolean(slot);
}

export function hint(popup, text) {
  /* The footer's left-hand slot: the keys this VIEW answers to. One
     popup can be two views — a story list and one story's messages —
     and a footer advertising the other one's keys is a footer lying. */
  const slot = $(".otk-popup__foot span", popup);
  if (slot) slot.textContent = text;
}

/** A screen's own action, answered for. Every `on*` handler and every
    promise nobody awaits goes through here: without it a request that
    fails inside a popup is an unhandled rejection, and the reader — who
    is looking at a modal, with the flow behind it — is told nothing at
    all. The sentence goes to the flow; the stack goes to the console,
    because a failure here is a bug, not an answer. */
export function guard(action) {
  if (!action) return action;
  return (...args) => {
    try {
      return Promise.resolve(action(...args)).catch(failed);
    } catch (e) {
      failed(e);
      return undefined;
    }
  };
}

function failed(e) {
  console.error(e);
  const sentence = String(e?.message ?? e);
  /* Where the reader is looking. A screen's failure said in the flow is
     a failure said BEHIND a modal — the panel covers it, and the write
     that did not happen reads as a click that did nothing. So it goes to
     the footer of the panel that is open, and to the flow only when
     none is. */
  const open = $$("dialog[open]").at(-1);
  if (open && footnote(open, sentence)) return;
  tell(sentence, "otk-error");
}

/** One live wiring per popup: a screen built again — a drill-in, a lens,
    a save — drops the last one's listeners before adding its own. The
    controller hangs on the popup because the popup is what outlives the
    call; several screens rely on that, so it is declared once, here. */
export function wiring(popup) {
  popup._wiring?.abort();
  return (popup._wiring = new AbortController()).signal;
}

/** The filter's keys, wired ONCE for every screen that has one. The Esc
    ladder is innermost-first, and a filter with text in it is a depth
    of its own: Esc empties it and goes no further — not even to the
    popup's own keydown, which is why this must be registered BEFORE it.
    `/` walks in from anywhere that is not already a field. A popup with
    no filter gets nothing. */
export function wireFilter(popup, { refilter, focus }, signal) {
  const filter = $(".otk-filter", popup);
  if (!filter) return;
  filter.value = "";
  filter.addEventListener("input", () => refilter(filter.value), { signal });
  popup.addEventListener(
    "keydown",
    (event) => {
      if (event.key === "Escape" && filter.value) {
        event.preventDefault();
        event.stopImmediatePropagation();
        filter.value = "";
        refilter("");
        focus();
      } else if (event.key === "/" && !event.target.matches("input, textarea")) {
        event.preventDefault();
        filter.focus();
      }
    },
    { signal },
  );
}

export function browser(popup, options) {
  /* Every callback a screen hands in is answered for, once, here — a
     row opened, a row deleted, a lens switched: all of them reach the
     session, and any of them can fail. */
  const { rows, drawRow, drawPreview, groupOf, drawGroup, search, onKey } = options;
  const onOpen = guard(options.onOpen);
  const onDelete = guard(options.onDelete);
  const onEdit = guard(options.onEdit);
  const onTab = guard(options.onTab);
  const onPivot = guard(options.onPivot);
  const onMove = options.onMove;
  const onBack = guard(options.onBack);
  const list = $(".otk-list", popup);
  const preview = $(".otk-preview", popup);
  let shown = rows;
  let cursor = 0;

  const signal = wiring(popup);

  /* Two steps, and the split is what makes a double click possible: the
     rows are BUILT when the data changes, and only MARKED when the
     cursor moves. Rebuilding on every selection replaced the row under
     the pointer between the two clicks, and a browser fires `dblclick`
     only when both land on the same element — so the second click went
     nowhere at all. */
  function mark() {
    // Captions are not rows: the cursor walks `.otk-row` alone, which
    // is what keeps a grouped list's index math straight.
    const drawn = $$(".otk-row", list);
    drawn.forEach((row, i) => {
      row.classList.toggle("is-selected", i === cursor);
      row.setAttribute("aria-selected", String(i === cursor));
    });
    // A screen without a per-row preview (the model picker draws its
    // provider panel once, beside the list) keeps whatever it drew.
    if (drawPreview) preview.replaceChildren(...(shown.length ? drawPreview(shown[cursor]) : []));
    if (shown.length) onMove?.(shown[cursor], cursor, shown.length);
    drawn[cursor]?.scrollIntoView({ block: "nearest" });
    // A rebuild destroys the row that was focused — the one an arrow key
    // moved off — and focus falls to `body`, outside the dialog, where
    // none of the keys this footer advertises can ever reach the handler
    // below.
    if (!popup.contains(document.activeElement)) list.focus();
  }

  function paint() {
    const nodes = [];
    shown.forEach((item, i) => {
      // A grouped list gets its caption before the first row under it —
      // drawn, never selected (see `mark`). A filter narrows the rows,
      // and a group with no row left drops out with them.
      if (groupOf && (i === 0 || groupOf(item) !== groupOf(shown[i - 1]))) {
        nodes.push(drawGroup(groupOf(item)));
      }
      const button = drawRow(item);
      button.addEventListener("click", () => {
        cursor = i;
        mark();
      });
      // Whatever `enter` does on a row, this does too: a list is
      // opened by keyboard and by mouse, and both are the same door.
      button.addEventListener("dblclick", () => onOpen?.(shown[i]));
      nodes.push(button);
    });
    list.replaceChildren(...nodes);
    mark();
  }

  let asked = 0;

  async function refilter(raw) {
    /* One request per keystroke, and they can answer out of order — a
       slower earlier one would paint over a later answer. Each carries
       its turn; only the newest paints, and none paints after this
       browser has been replaced (the panel it draws into belongs to the
       popup, not to us). */
    const mine = ++asked;
    const needle = raw.trim().toLowerCase();
    let matched;
    if (search && needle) {
      /* The whole filter, answered below both frontends: buried content
         OR the row's own face — `api.stories.search` owns the union, so
         this browser and the terminal's can never find different
         stories. A screen without a `search` filters its rows' own
         haystack instead. */
      const found = new Set(await search(needle));
      matched = rows.filter((item) => found.has(item.id));
    } else {
      matched = needle ? rows.filter((item) => item.haystack.includes(needle)) : rows;
    }
    if (mine !== asked || signal.aborted) return;
    shown = matched;
    cursor = Math.min(cursor, Math.max(0, shown.length - 1));
    paint();
  }

  // Registered first, so the filter's Esc outranks the ladder below.
  wireFilter(popup, { refilter, focus: () => list.focus() }, signal);
  popup.addEventListener(
    "keydown",
    (event) => {
      /* Esc reaching here found the filter empty (`wireFilter` consumed
         it otherwise): what is left inside is a drill-in's way back,
         and past that the popup itself, which `app.js` closes. */
      if (event.key === "Escape") {
        if (onBack) {
          event.preventDefault();
          event.stopPropagation();
          onBack();
        }
        return;
      }
      // A key with a modifier belongs to the browser: ⌘R is a reload,
      // not a reset, and `preventDefault` on one is taking it.
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.target.matches("input, textarea")) return;
      // A row in the preview — a field, a message's edit — carries its
      // own Enter, and every one of them says "enter to edit" on its
      // face. Taking the key here would run the LIST's action instead.
      if (event.target.closest(".otk-preview")) return;
      if (event.key === "ArrowRight" && onPivot && shown.length) {
        // The lore footer's `→`: the same door the row's own pivot
        // button opens, for the reader who is on the keys.
        event.preventDefault();
        onPivot(shown[cursor]);
      } else if (event.key === "Tab" && onTab) {
        // The lore footer advertises it, and a list is not a form: with
        // the rows focused there is nothing else here to tab to.
        event.preventDefault();
        onTab();
      } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const step = event.key === "ArrowDown" ? 1 : -1;
        cursor = Math.max(0, Math.min(shown.length - 1, cursor + step));
        mark();
      } else if (event.key === "Enter" && shown.length) {
        event.preventDefault();
        onOpen?.(shown[cursor]);
      } else if (event.key === "e" && onEdit && shown.length) {
        // The one row-level write that is not what Enter does: a message
        // is corrected where it is shown, and the footer says so.
        event.preventDefault();
        onEdit(shown[cursor]);
      } else if ((event.key === "Delete" || event.key === "Backspace") && shown.length) {
        event.preventDefault();
        onDelete?.(shown[cursor]);
      } else if (onKey?.(event, shown[cursor])) {
        // A screen's own key — the picker's `l`/`u` — asked LAST, so it
        // can never shadow the kit's.
        event.preventDefault();
      }
    },
    { signal },
  );

  paint();
  /* Where a browser is read from. `showModal` focuses the first
     focusable descendant — the filter, where every motion key below is
     deliberately ignored — unless something claims it with `autofocus`,
     which is the platform's own way to say "start here". The direct
     call covers the other case: a browser rebuilt on a popup that is
     already open (a drill-in, a lens, a save). */
  list.setAttribute("autofocus", "");
  list.focus();
  return {
    select(matches) {
      const found = shown.findIndex(matches);
      if (found >= 0) {
        cursor = found;
        mark();
      }
    },
    /** The row the cursor is on — what a header button acts on, since
        a button outside the list cannot know where the list is. */
    current() {
      return shown[cursor];
    },
    /** And what `enter` does to it, for the button that says so. */
    open() {
      if (shown.length) onOpen?.(shown[cursor]);
    },
  };
}

/** The edit-in-place discipline every editor shares: whatever ends it
    ends it once. A blur AFTER a save must not put the old row back over
    the redraw the save is doing, so the first end — Esc, a click
    elsewhere, the save itself — settles it. Esc is stopped where it is
    answered, because the innermost layer unwinds first: the dialog
    above must not take a half-edited field for a close. `saves` names
    the save key, because the shapes disagree — Ctrl+S in a block of
    text, where Enter is a newline; Enter in a one-line field. */
export function editingKeys(field, { saves, save, cancel }) {
  let settled = false;
  const done = () => {
    if (settled) return;
    settled = true;
    cancel();
  };
  field.addEventListener("blur", done);
  field.addEventListener("keydown", async (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      done();
    } else if (save && saves(event)) {
      event.preventDefault();
      settled = true;
      await save();
    }
  });
}

/** Edit a text where it is displayed: the row becomes the editor, Ctrl+S
    saves, Esc puts the row back. */
export function inlineEditor(anchor, { text, caption, save: write, readonly = false }) {
  const save = guard(write);
  const editor = element("div", "otk-editor");
  const area = element("textarea", "otk-editor__input");
  area.value = text;
  // A derived field opens to be READ: the same block, the same keys to
  // leave it by, and nothing that pretends it could be saved.
  area.readOnly = readonly;
  const foot = element("p", "otk-editor__foot", caption);
  foot.append(span("otk-meta", readonly ? " esc close" : " ctrl+s save · esc cancel"));
  editor.append(area, foot);
  anchor.replaceWith(editor);
  area.focus();
  autosize(area);
  /* Clicking away is cancelling: a field left without saving is left
     alone, which is the same promise the picker's fields and the
     settings panel's make. */
  editingKeys(area, {
    saves: (event) => !readonly && event.key === "s" && (event.metaKey || event.ctrlKey),
    save: () => save(area.value),
    cancel: () => {
      editor.replaceWith(anchor);
      // The focused textarea has just left the document, so focus falls
      // to `body` — outside the dialog, where none of the keys this
      // screen advertises would arrive. Give it back to the rows, or to
      // the row the editor replaced, which is a button and takes focus.
      const dialog = anchor.closest?.("dialog");
      ($(".otk-list", dialog) ?? $("[tabindex]", dialog) ?? anchor)?.focus?.();
    },
  });
}

/** One of the markup's ask dialogs, by name. Its buttons carry
    `data-choice`; the answer is which one was pressed, or null for Esc
    and the scrim. Copy is never read — renaming a button must not
    change what it does. */
export function ask(name, fill) {
  const dialog = $(`dialog[data-dialog="${name}"]`);
  fill?.(dialog);
  return new Promise((resolve) => {
    const wired = new AbortController();
    const settle = (choice) => {
      wired.abort();
      dialog.close();
      resolve(choice);
    };
    for (const button of $$("[data-choice]", dialog)) {
      button.addEventListener("click", () => settle(button.dataset.choice), {
        signal: wired.signal,
      });
    }
    dialog.addEventListener("close", () => settle(null), { signal: wired.signal, once: true });
    dialog.showModal();
  });
}
