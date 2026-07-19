// Injects the ::highlight(hl-*) paint rules at runtime instead of via
// globals.css, because Turbopack/Lightning-CSS (build-time) doesn't
// recognize the ::highlight() pseudo-element and its warning poisons the
// .next cache. Browsers DO support it, so runtime injection is safe.
let injected = false;
const STYLE_ID = "smv2-highlight-rules";

export function ensureHighlightStyles(): void {
  if (injected || typeof document === "undefined") return;
  if (document.getElementById(STYLE_ID)) {
    injected = true;
    return;
  }
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = [
    "::highlight(hl-yellow){background-color:var(--highlight-yellow);}",
    "::highlight(hl-green){background-color:var(--highlight-green);}",
    "::highlight(hl-blue){background-color:var(--highlight-blue);}",
    "::highlight(hl-pink){background-color:var(--highlight-pink);}",
  ].join("");
  document.head.appendChild(style);
  injected = true;
}
