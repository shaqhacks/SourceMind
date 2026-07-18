import { describe, expect, it } from "vitest";

describe("CSS Custom Highlight API shim (jsdom)", () => {
  it("exposes CSS.highlights as a Map-like registry", () => {
    expect(typeof CSS).toBe("object");
    expect(CSS.highlights).toBeDefined();
    expect(typeof CSS.highlights.set).toBe("function");
    expect(typeof CSS.highlights.delete).toBe("function");
  });

  it("constructs a Highlight from ranges", () => {
    const r = document.createRange();
    const h = new Highlight(r);
    expect(h).toBeInstanceOf(Highlight);
    CSS.highlights.set("hl-yellow", h);
    expect(CSS.highlights.get("hl-yellow")).toBe(h);
    CSS.highlights.delete("hl-yellow");
    expect(CSS.highlights.has("hl-yellow")).toBe(false);
  });
});
