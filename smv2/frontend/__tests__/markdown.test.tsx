import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Markdown from "@/components/Markdown";

describe("Markdown", () => {
  it("renders headings with deep-linkable ids and a hover anchor link", () => {
    render(<Markdown>{"# Hello World\n\n## Sub Section"}</Markdown>);

    const h1 = screen.getByRole("heading", { level: 1, name: /hello world/i });
    expect(h1).toHaveAttribute("id", "hello-world");
    // Scoped to h1: every heading gets an anchor with the same
    // "Link to this section" label, so an unscoped query would match both.
    const h1Anchor = within(h1).getByRole("link", { name: /link to this section/i });
    expect(h1Anchor).toHaveAttribute("href", "#hello-world");

    const h2 = screen.getByRole("heading", { level: 2, name: /sub section/i });
    expect(h2).toHaveAttribute("id", "sub-section");
  });

  it("renders GFM tables", () => {
    const table = "| A | B |\n| --- | --- |\n| 1 | 2 |\n";
    render(<Markdown>{table}</Markdown>);

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "A" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "1" })).toBeInTheDocument();
  });

  it("renders GFM strikethrough and task lists", () => {
    render(<Markdown>{"~~struck~~\n\n- [x] done\n- [ ] todo"}</Markdown>);

    expect(screen.getByText("struck").tagName).toBe("DEL");
    const checkboxes = screen.getAllByRole("checkbox");
    expect(checkboxes).toHaveLength(2);
    expect(checkboxes[0]).toBeChecked();
    expect(checkboxes[1]).not.toBeChecked();
  });

  it("renders a fenced code block inside a scrollable pre", () => {
    render(<Markdown>{"```js\nconst x = 1;\n```"}</Markdown>);

    const code = screen.getByText("const x = 1;");
    expect(code.tagName).toBe("CODE");
    expect(code.parentElement?.tagName).toBe("PRE");
  });

  it("renders blockquotes", () => {
    render(<Markdown>{"> A quoted line"}</Markdown>);
    expect(screen.getByText("A quoted line").closest("blockquote")).toBeInTheDocument();
  });

  it("renders pymupdf4llm's <sup>/<u> stacked-fraction HTML as real elements, not literal text", () => {
    render(<Markdown>{"<sup><u>30</u></sup> 46"}</Markdown>);

    const underline = screen.getByText("30");
    expect(underline.tagName).toBe("U");
    const sup = underline.closest("sup");
    expect(sup).not.toBeNull();
    expect(sup?.textContent).toBe("30");

    // No literal tag text anywhere in the rendered output.
    expect(document.body.textContent).not.toContain("<sup>");
    expect(document.body.textContent).not.toContain("<u>");
  });

  it("renders inline HTML <sup>/<sub>/<u>/<b>/<i> with no attributes forwarded", () => {
    render(
      <Markdown>
        {'<sup class="evil" title="x">up</sup> <b id="y">bold</b> <u data-foo="z">under</u>'}
      </Markdown>,
    );

    const sup = screen.getByText("up");
    expect(sup.tagName).toBe("SUP");
    expect(sup.attributes.length).toBe(0);

    const b = screen.getByText("bold");
    expect(b.tagName).toBe("B");
    expect(b.attributes.length).toBe(0);

    const u = screen.getByText("under");
    expect(u.tagName).toBe("U");
    expect(u.attributes.length).toBe(0);
  });

  describe("sanitizes dangerous HTML embedded in the (untrusted, PDF-extracted) source", () => {
    it("strips <script> and its content entirely", () => {
      render(<Markdown>{"before <script>window.__pwned = true;</script> after"}</Markdown>);

      expect(document.querySelector("script")).not.toBeInTheDocument();
      expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined();
      expect(document.body.textContent).not.toContain("__pwned");
    });

    it("strips <img> entirely, including onerror and other attributes", () => {
      render(<Markdown>{"before <img src=x onerror=\"window.__pwned=true\"> after"}</Markdown>);

      expect(screen.queryByRole("img")).not.toBeInTheDocument();
      expect(document.querySelector("img")).not.toBeInTheDocument();
      expect(document.querySelector("[onerror]")).not.toBeInTheDocument();
      expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined();
    });

    it("strips <iframe>", () => {
      render(<Markdown>{'before <iframe src="https://evil.example"></iframe> after'}</Markdown>);

      expect(document.querySelector("iframe")).not.toBeInTheDocument();
    });

    it("drops javascript: hrefs but keeps markdown-native links working", () => {
      render(
        <Markdown>
          {"[click me](javascript:window.__pwned=true) and [safe](https://example.com/page)"}
        </Markdown>,
      );

      const dangerous = screen.getByText("click me").closest("a");
      expect(dangerous).not.toBeNull();
      expect(dangerous?.hasAttribute("href")).toBe(false);
      expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined();

      const safe = screen.getByRole("link", { name: "safe" });
      expect(safe).toHaveAttribute("href", "https://example.com/page");
    });
  });
});
