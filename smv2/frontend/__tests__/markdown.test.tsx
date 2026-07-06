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

  describe("KaTeX math (prompts v2 generated content)", () => {
    it("renders inline $...$ math as a real .katex element, not literal dollar text", () => {
      const { container } = render(<Markdown>{"The area is $\\pi r^2$ exactly."}</Markdown>);

      const katex = container.querySelector(".katex");
      expect(katex).not.toBeNull();
      expect(document.body.textContent).not.toContain("$\\pi r^2$");
    });

    it("renders display $$...$$ math as a centered .katex-display block", () => {
      const { container } = render(<Markdown>{"$$\nx = \\frac{1}{2}\n$$"}</Markdown>);

      expect(container.querySelector(".katex-display")).not.toBeNull();
      expect(container.querySelector(".katex")).not.toBeNull();
    });

    it("does not box a display equation in the regular fenced-code-block chrome", () => {
      const { container } = render(<Markdown>{"$$\nx = 1\n$$"}</Markdown>);

      // The math container must not pick up the code-block styling (which
      // would visually clash with a typeset equation) — no bordered <pre>
      // wrapping it, even though remark-math's own hast output nests the
      // math inside a <code> that a <pre> would normally wrap.
      const pre = container.querySelector("pre");
      expect(pre).toBeNull();
    });

    it("with trust:false, a malicious \\href never becomes a real (or javascript:) link", () => {
      render(<Markdown>{"$\\href{javascript:window.__pwned=true}{click}$"}</Markdown>);

      expect(document.querySelector('a[href^="javascript:"]')).not.toBeInTheDocument();
      expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined();
    });

    it("keeps the rest of the sanitize suite green alongside math", () => {
      render(
        <Markdown>
          {"$x$\n\nbefore <script>window.__pwned = true;</script> after"}
        </Markdown>,
      );

      expect(document.querySelector(".katex")).not.toBeNull();
      expect(document.querySelector("script")).not.toBeInTheDocument();
      expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined();
    });
  });

  describe("extracted images (backend-served, gated by src pattern)", () => {
    it("renders a valid /api/courses/{id}/images/{file} reference with an API_BASE-prefixed, lazy-loaded <img>", () => {
      render(<Markdown>{"![Figure 1](/api/courses/course-1/images/fig1.png)"}</Markdown>);

      const img = screen.getByRole("img", { name: "Figure 1" });
      expect(img).toHaveAttribute("src", "http://localhost:8000/api/courses/course-1/images/fig1.png");
      expect(img).toHaveAttribute("loading", "lazy");
    });

    it("refuses an external http(s) image", () => {
      render(<Markdown>{"![evil](https://evil.example/tracker.png)"}</Markdown>);

      expect(screen.queryByRole("img")).not.toBeInTheDocument();
    });

    it("refuses a data: URI image", () => {
      render(<Markdown>{"![evil](data:image/png;base64,aaaa)"}</Markdown>);

      expect(screen.queryByRole("img")).not.toBeInTheDocument();
    });

    it("refuses a protocol-relative image", () => {
      render(<Markdown>{"![evil](//evil.example/tracker.png)"}</Markdown>);

      expect(screen.queryByRole("img")).not.toBeInTheDocument();
    });

    it("refuses a raw-HTML <img> even when onerror is stripped, unless its src matches the pattern", () => {
      render(<Markdown>{'before <img src="/not/our/pattern.png" onerror="window.__pwned=true"> after'}</Markdown>);

      expect(screen.queryByRole("img")).not.toBeInTheDocument();
      expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined();
    });
  });
});
