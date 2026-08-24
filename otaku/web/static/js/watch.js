/* Reloading the page as the files it is made of change.

   Held open for as long as the tab is: an edit to the reader's own
   `custom.css` shows up on its own, and so does a page whose otaku was
   restarted on a newer build. Nothing about it is a development mode —
   what is on disk is what the browser has, which is the same rule the
   assets are served under. */

import { $$ } from "./dom.js";

export function watchForChanges() {
  const watch = new EventSource("/api/watch");
  let connected = false;

  watch.addEventListener("open", () => {
    // A second open means the server restarted under us: new Python, so
    // the page it served is stale too.
    if (connected) location.reload();
    connected = true;
  });

  watch.addEventListener("message", (event) => {
    if (!event.data.endsWith(".css")) {
      location.reload();
      return;
    }
    // A stylesheet swap keeps the page: the open popup, the scroll
    // position and anything in flight all survive it.
    for (const link of $$('link[rel="stylesheet"]')) {
      link.href = `${link.href.split("?")[0]}?v=${Date.now()}`;
    }
  });
}
