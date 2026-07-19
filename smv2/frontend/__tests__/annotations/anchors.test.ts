import { describe, expect, it, beforeEach } from "vitest";
import { selectorFromRange, rangeForSelector, resolvePdfPageSelection } from "@/lib/annotations/anchors";

function container(html: string): HTMLElement {
  const el = document.createElement("div");
  el.innerHTML = html;
  document.body.appendChild(el);
  return el;
}

// Build a Range spanning the first occurrence of `needle` within a single text node.
function rangeOf(el: HTMLElement, needle: string, nth = 0): Range {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let seen = 0;
  let node: Node | null;
  while ((node = walker.nextNode())) {
    const text = node.textContent ?? "";
    let from = 0;
    for (;;) {
      const i = text.indexOf(needle, from);
      if (i === -1) break;
      if (seen === nth) {
        const r = document.createRange();
        r.setStart(node, i);
        r.setEnd(node, i + needle.length);
        return r;
      }
      seen++;
      from = i + needle.length;
    }
  }
  throw new Error(`needle not found: ${needle}`);
}

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("selectorFromRange", () => {
  it("captures exact plus surrounding context", () => {
    const el = container("<p>The mitochondria is the powerhouse of the cell.</p>");
    const sel = selectorFromRange(el, rangeOf(el, "powerhouse"));
    expect(sel).not.toBeNull();
    expect(sel!.exact).toBe("powerhouse");
    expect(sel!.prefix.endsWith("the ")).toBe(true);
    expect(sel!.suffix.startsWith(" of")).toBe(true);
    expect(sel!.occurrence).toBe(0);
  });

  it("returns null for a collapsed range", () => {
    const el = container("<p>hello</p>");
    const r = document.createRange();
    r.setStart(el.firstChild!.firstChild!, 2);
    r.collapse(true);
    expect(selectorFromRange(el, r)).toBeNull();
  });

  it("numbers a repeated phrase by occurrence", () => {
    const el = container("<p>ion channel ... ion channel ... ion channel</p>");
    expect(selectorFromRange(el, rangeOf(el, "ion channel", 0))!.occurrence).toBe(0);
    expect(selectorFromRange(el, rangeOf(el, "ion channel", 2))!.occurrence).toBe(2);
  });

  it("spans across element boundaries", () => {
    const el = container("<p>alpha <strong>beta</strong> gamma</p>");
    // Select "beta gamma" across the <strong> boundary.
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const beta = walker.nextNode() && walker.currentNode; // "alpha "
    // simpler: build range from "beta" start to end of " gamma"
    const strongText = el.querySelector("strong")!.firstChild!;
    const tailText = el.querySelector("p")!.childNodes[2]; // " gamma"
    const r = document.createRange();
    r.setStart(strongText, 0);
    r.setEnd(tailText, tailText.textContent!.length);
    const sel = selectorFromRange(el, r);
    expect(sel!.exact).toBe("beta gamma");
  });

  it("captures a triple-click-style selectNodeContents range (Element start AND end boundaries)", () => {
    const el = container("<p>the whole paragraph text</p>");
    const p = el.querySelector("p")!;
    const r = document.createRange();
    r.selectNodeContents(p);
    // Sanity: selectNodeContents anchors both boundaries on the Element, not
    // a Text node — this is exactly the shape flatIndexOf used to miss.
    expect(r.startContainer).toBe(p);
    expect(r.endContainer).toBe(p);
    const sel = selectorFromRange(el, r);
    expect(sel).not.toBeNull();
    expect(sel!.exact).toBe("the whole paragraph text");
  });

  it("captures a range with an Element-anchored start boundary and Text-anchored end boundary", () => {
    const el = container("<p>the whole paragraph text</p>");
    const p = el.querySelector("p")!;
    const textNode = p.firstChild as Text;
    const k = "the whole".length;
    const r = document.createRange();
    r.setStart(p, 0); // Element boundary: before p's first child.
    r.setEnd(textNode, k);
    const sel = selectorFromRange(el, r);
    expect(sel).not.toBeNull();
    expect(sel!.exact).toBe("the whole");
  });
});

describe("rangeForSelector round-trip", () => {
  it("relocates the same text", () => {
    const el = container("<p>The mitochondria is the powerhouse of the cell.</p>");
    const sel = selectorFromRange(el, rangeOf(el, "powerhouse"))!;
    const r = rangeForSelector(el, sel)!;
    expect(r).not.toBeNull();
    expect(r.toString()).toBe("powerhouse");
  });

  it("round-trips a selectNodeContents (Element-boundary) capture back to the full paragraph text", () => {
    const el = container("<p>the whole paragraph text</p>");
    const p = el.querySelector("p")!;
    const captureRange = document.createRange();
    captureRange.selectNodeContents(p);
    const sel = selectorFromRange(el, captureRange)!;
    expect(sel).not.toBeNull();
    const r = rangeForSelector(el, sel)!;
    expect(r).not.toBeNull();
    expect(r.toString()).toBe("the whole paragraph text");
  });

  it("relocates the correct occurrence of a repeat", () => {
    const el = container("<p>ion channel A ion channel B ion channel C</p>");
    const sel = selectorFromRange(el, rangeOf(el, "ion channel", 2))!;
    const r = rangeForSelector(el, sel)!;
    // The 3rd occurrence is immediately followed by " C".
    const after = r.endContainer.textContent!.slice(r.endOffset, r.endOffset + 2);
    expect(after).toBe(" C");
  });

  it("returns null when the text is absent", () => {
    const el = container("<p>nothing here</p>");
    expect(rangeForSelector(el, { exact: "absent", prefix: "", suffix: "", occurrence: 0 })).toBeNull();
  });

  it("returns null when occurrence is out of range", () => {
    const el = container("<p>once</p>");
    expect(rangeForSelector(el, { exact: "once", prefix: "", suffix: "", occurrence: 5 })).toBeNull();
  });
});

describe("resolvePdfPageSelection", () => {
  it("resolves the page number and a selector scoped to the [data-pdf-page] container", () => {
    const root = container(
      '<div data-pdf-page="3"><p>The mitochondria is the powerhouse of the cell.</p></div>',
    );
    const r = rangeOf(root, "powerhouse");
    const result = resolvePdfPageSelection(r.startContainer, r.endContainer, r);
    expect(result).not.toBeNull();
    expect(result!.page).toBe(3);
    expect(result!.selector.exact).toBe("powerhouse");
  });

  it("returns null when there is no [data-pdf-page] ancestor", () => {
    const root = container("<p>The mitochondria is the powerhouse of the cell.</p>");
    const r = rangeOf(root, "powerhouse");
    expect(resolvePdfPageSelection(r.startContainer, r.endContainer, r)).toBeNull();
  });

  it("returns null when the focus node falls outside the anchor's page container (cross-page selection)", () => {
    const root = container(
      '<div data-pdf-page="1"><p id="a">alpha beta</p></div>' +
        '<div data-pdf-page="2"><p id="b">gamma delta</p></div>',
    );
    const pageOneText = root.querySelector("#a")!.firstChild as Text;
    const pageTwoText = root.querySelector("#b")!.firstChild as Text;
    const range = document.createRange();
    range.setStart(pageOneText, 0);
    range.setEnd(pageTwoText, 5);
    expect(resolvePdfPageSelection(pageOneText, pageTwoText, range)).toBeNull();
  });

  it("returns null for a non-numeric data-pdf-page value", () => {
    const root = container('<div data-pdf-page="not-a-number"><p>hello world</p></div>');
    const r = rangeOf(root, "hello");
    expect(resolvePdfPageSelection(r.startContainer, r.endContainer, r)).toBeNull();
  });

  it("returns null for a collapsed range (selectorFromRange itself rejects it)", () => {
    const root = container('<div data-pdf-page="1"><p>hello</p></div>');
    const textNode = root.querySelector("p")!.firstChild as Text;
    const range = document.createRange();
    range.setStart(textNode, 1);
    range.collapse(true);
    expect(resolvePdfPageSelection(textNode, textNode, range)).toBeNull();
  });

  it("returns null when anchorNode is null", () => {
    const root = container('<div data-pdf-page="1"><p>hello</p></div>');
    const r = rangeOf(root, "hello");
    expect(resolvePdfPageSelection(null, r.endContainer, r)).toBeNull();
  });
});
