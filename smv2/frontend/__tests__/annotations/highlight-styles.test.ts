import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const STYLE_ID = "smv2-highlight-rules";

function getStyleEl(): HTMLElement | null {
  return document.getElementById(STYLE_ID);
}

describe("ensureHighlightStyles", () => {
  beforeEach(() => {
    // Each test re-imports the module fresh so the internal `injected`
    // flag starts false, matching a real page load.
    vi.resetModules();
    document.getElementById(STYLE_ID)?.remove();
  });

  afterEach(() => {
    document.getElementById(STYLE_ID)?.remove();
  });

  it("appends a <style id=smv2-highlight-rules> to document.head with all four ::highlight(hl-<color>) rules", async () => {
    const { ensureHighlightStyles } = await import("@/lib/annotations/highlightStyles");

    ensureHighlightStyles();

    const style = getStyleEl();
    expect(style).not.toBeNull();
    expect(style?.tagName).toBe("STYLE");
    expect(style?.parentElement).toBe(document.head);

    const css = style?.textContent ?? "";
    expect(css).toContain("::highlight(hl-yellow){background-color:var(--highlight-yellow);}");
    expect(css).toContain("::highlight(hl-green){background-color:var(--highlight-green);}");
    expect(css).toContain("::highlight(hl-blue){background-color:var(--highlight-blue);}");
    expect(css).toContain("::highlight(hl-pink){background-color:var(--highlight-pink);}");
  });

  it("calling it twice does not create a second style element", async () => {
    const { ensureHighlightStyles } = await import("@/lib/annotations/highlightStyles");

    ensureHighlightStyles();
    ensureHighlightStyles();

    expect(document.head.querySelectorAll(`#${STYLE_ID}`).length).toBe(1);
  });

  it("a style element already present in the head (e.g. from a prior mount) is treated as already injected", async () => {
    const preexisting = document.createElement("style");
    preexisting.id = STYLE_ID;
    document.head.appendChild(preexisting);

    const { ensureHighlightStyles } = await import("@/lib/annotations/highlightStyles");
    ensureHighlightStyles();

    expect(document.head.querySelectorAll(`#${STYLE_ID}`).length).toBe(1);
  });
});
