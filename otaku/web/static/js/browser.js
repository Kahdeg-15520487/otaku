/* The shapes every screen is built from: the list-and-detail browser,
   the editors that open where the text already is, and the ask dialogs.

   The browser takes its rows and its drawing callbacks and owns nothing
   else — the terminal needed a base class with hooks for the same job,
   and a page does not. A grouped list (the model picker) hands in
   `groupOf`/`drawGroup` and the captions are drawn between the rows
   without ever being rows: the cursor walks `.otk-row` alone.

   The kit finds its parts by structural hooks, not by look: `[data-list]`
   is the scroller it fills, `[data-detail]` the pane beside it,
   `[data-note]` the footer's one slot — the fact this view stands on. A
   panel with two lists on two tabs hands in `root`, the pane the
   browser lives in. */

import { $, $$, autosize, element, span } from "./dom.js";
import { tell } from "./status.js";

/* Every popup in the markup, by the command that opens it. They live here
   because a screen module must not have to import chrome from a sibling
   screen module — `browser.js` is what a screen is built FROM. */
export const popups = new Map($$("dialog[data-popup]").map((d) => [d.dataset.popup, d]));

export function closeAll() {
  for (const dialog of $$("dialog[open]")) dialog.close();
}

export function footnote(popup, text) {
  /* The footer's fact slot: the panel's own standing fact, set every
     time a screen opens — and what a WRITE answered with, carried into
     the redraw the write triggers, or the standing fact would go back
     over the answer milliseconds after it appeared. Says whether there
     was a slot at all: a popup without a footer is a real shape (the
     ask dialogs), and its notices go to the flow instead. */
  const slot = $("[data-note]", popup);
  if (slot) slot.textContent = text;
  return Boolean(slot);
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

/** One live wiring per popup: a screen built again — a tab, a lens, a
    save — drops the last one's listeners before adding its own. The
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
    `/` walks in from anywhere that is not already a field. A view with
    no filter gets nothing. */
export function wireFilter(popup, { refilter, focus }, signal, root = popup) {
  const filter = $(".otk-filter", root);
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
  const { rows, drawRow, drawPreview, groupOf, drawGroup, search, onKey, empty } = options;
  const onOpen = guard(options.onOpen);
  const onDelete = guard(options.onDelete);
  const onEdit = guard(options.onEdit);
  const onTab = guard(options.onTab);
  const onPivot = guard(options.onPivot);
  const onMove = options.onMove;
  const onBack = guard(options.onBack);
  // The pane this browser lives in: the whole popup for a single-view
  // panel, one `[data-pane]` of it for a tabbed one.
  const root = options.root ?? popup;
  const list = $("[data-list]", root);
  const preview = $("[data-detail]", root);
  /* The verbs under the pane. They are filled by `drawPreview`, which is
     the SELECTED row's — so with no row selected they must be empty:
     verbs left standing over an empty list still act on whatever was
     highlighted before, and Delete cannot be aimed at a row nobody can
     see. */
  const actions = $("[data-actions]", root);
  let shown = rows;
  let cursor = 0;
  let filtering = "";

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
      row.setAttribute("aria-selected", String(i === cursor));
    });
    // A screen without a per-row preview keeps whatever it drew.
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
    /* A list with nothing in it says WHAT is missing and the way out —
       a first run and a filter that matched nothing are different
       absences, and a blank column tells a reader neither. */
    if (!shown.length && empty) {
      const { line, hint: way } = empty(Boolean(filtering));
      const box = element("div", "otk-empty");
      box.append(span("otk-empty__line", line));
      if (way) box.append(span("otk-empty__hint", way));
      list.replaceChildren(box);
      if (drawPreview) preview.replaceChildren();
      actions?.replaceChildren();
      return;
    }
    shown.forEach((item, i) => {
      // A grouped list gets its caption before the first row under it —
      // drawn, never selected (see `mark`). A filter narrows the rows,
      // and a group with no row left drops out with them.
      if (groupOf && (i === 0 || groupOf(item) !== groupOf(shown[i - 1]))) {
        nodes.push(...[drawGroup(groupOf(item))].flat());
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
    filtering = needle;
    let matched;
    if (search && needle) {
      /* The whole filter, answered below both frontends: buried content
         OR the row's own face — the listing's own `q` owns the union, so
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
  wireFilter(popup, { refilter, focus: () => list.focus() }, signal, root);
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
      // A control in the detail pane — a field, a message's edit —
      // carries its own Enter. Taking the key here would run the LIST's
      // action instead.
      if (event.target.closest("[data-detail], [data-reading], [data-margin]")) return;
      if (event.key === "ArrowRight" && onPivot && shown.length) {
        event.preventDefault();
        onPivot(shown[cursor]);
      } else if (event.key === "Tab" && onTab) {
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
     already open (a tab, a lens, a save). */
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

/** A text that is edited where it is READ: the field IS the text. It
    carries the same class the paragraph would have, so it inherits that
    face, that measure and that box exactly — a summary, a journal entry
    and a description all edit identically and nothing reflows when a
    reader puts the caret in one. At rest a faint underline says it can
    be edited; with the caret in it, a white ground says it is open.

    Ctrl+S saves. Esc puts the stored text back, and so does clicking
    away: a field left unsaved is left alone, which is the promise every
    field in the app makes. `caption` is the line beside it, which says
    what state the field is in for as long as it is dirty. */
export function editable(className, { text, save: write, readonly = false, line = false }) {
  const save = guard(write);
  const field = element("textarea", `${className} otk-editable`.trim());
  field.value = text ?? "";
  field.readOnly = readonly;
  if (readonly) return field;
  field.spellcheck = false;

  field.addEventListener("blur", () => {
    // Clicking away is leaving it alone: the stored text comes back.
    field.value = text ?? "";
  });
  field.addEventListener("keydown", async (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      field.value = text ?? "";
      field.blur();
      return;
    }
    // A value that is one line long is finished by Enter; a passage of
    // prose needs Enter for its paragraphs, and is finished by ctrl+s.
    const commit =
      (line && event.key === "Enter" && !event.shiftKey) ||
      (event.key === "s" && (event.metaKey || event.ctrlKey));
    if (commit) {
      event.preventDefault();
      if (field.value === text) return field.blur();
      await save(field.value);
    }
  });
  return field;
}

/** A field with the line that belongs under it: the name of what it
    holds while it rests, and how to commit it while the caret is in it.
    The swap is the browser's own (`:focus-within`), so there is no state
    to keep, and the keys named here are the ones `editable` binds. */
export function edited(field, name) {
  const box = element("div", "otk-edit");
  const editing = element("span", "otk-edit__hint otk-edit__hint--editing");
  editing.append(
    span("", "editing"),
    span("otk-edit__key", "ctrl+s saves"),
    span("otk-edit__key", "esc discards"),
  );
  box.append(field, element("span", "otk-edit__hint otk-edit__hint--resting", name), editing);
  return box;
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
    /* Enter is the dialog's ACTION, wherever the focus is — the button
       a reader would press. It never cancels: leaving without answering
       is Esc's, and only Esc's. A textarea keeps its own Enter, because
       there the key is a newline. */
    dialog.addEventListener(
      "keydown",
      (event) => {
        if (event.key !== "Enter" || event.shiftKey) return;
        if (event.target.matches("textarea")) return;
        const action = $$("[data-choice]", dialog).findLast(
          (button) => button.dataset.choice !== "cancel",
        );
        if (!action) return;
        event.preventDefault();
        settle(action.dataset.choice);
      },
      { signal: wired.signal },
    );
    dialog.addEventListener("close", () => settle(null), { signal: wired.signal, once: true });
    dialog.showModal();
  });
}
