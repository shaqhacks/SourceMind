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

  it("does not render raw HTML embedded in the source", () => {
    render(<Markdown>{'Before <img src=x onerror="window.__pwned=true"> after'}</Markdown>);

    // No <img> was created — the tag shows up as literal escaped text.
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText(/before/i).textContent).toContain("<img");
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined();
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
});
