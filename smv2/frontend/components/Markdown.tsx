"use client";

import type { ComponentPropsWithoutRef } from "react";
import ReactMarkdown, { type Components, type ExtraProps } from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";

type HeadingTag = "h1" | "h2" | "h3" | "h4" | "h5" | "h6";

function makeHeading(Tag: HeadingTag) {
  function Heading({
    id,
    className,
    children,
    node: _node,
    ...rest
  }: ComponentPropsWithoutRef<HeadingTag> & ExtraProps) {
    return (
      <Tag id={id} className={`group relative scroll-mt-20 ${className ?? ""}`} {...rest}>
        {children}
        {id ? (
          <a
            href={`#${id}`}
            aria-label="Link to this section"
            className="ml-2 text-muted-foreground no-underline opacity-0 transition-opacity group-hover:opacity-100"
          >
            #
          </a>
        ) : null}
      </Tag>
    );
  }
  Heading.displayName = `Markdown${Tag.toUpperCase()}`;
  return Heading;
}

// Inline formatting tags pymupdf4llm emits as literal HTML (stacked
// fractions/superscripts in math workbooks) plus the ones GFM already
// produces from `**bold**`/`*em*` syntax. rehype-sanitize's default schema
// allows a handful of harmless-but-unnecessary attributes (id, title, lang,
// ...) on every allowed tag via its `'*'` wildcard, and the schema has no
// per-tag opt-out from that wildcard (a tag-specific `[]` entry still falls
// back to it — see hast-util-sanitize's `properties()`). Rather than rely on
// the schema alone for these, they render as bare tags that forward only
// `children`, so no attribute ever reaches the DOM for them regardless of
// what the sanitize schema's wildcard would otherwise let through.
type PlainInlineTag = "u" | "sup" | "sub" | "b" | "i" | "em" | "strong";

function makePlainInline(Tag: PlainInlineTag) {
  function PlainInline({ children }: ComponentPropsWithoutRef<PlainInlineTag> & ExtraProps) {
    return <Tag>{children}</Tag>;
  }
  PlainInline.displayName = `Markdown${Tag.toUpperCase()}`;
  return PlainInline;
}

function Break(_props: ComponentPropsWithoutRef<"br"> & ExtraProps) {
  return <br />;
}

// react-markdown always injects a `node` (the hast AST node) into every
// custom component's props alongside the real HTML attributes. It must be
// destructured out (never left in a `...rest` that gets spread onto the
// DOM element) or React renders an invalid `node="[object Object]"`
// attribute — every component below does this explicitly.
const components: Components = {
  h1: makeHeading("h1"),
  h2: makeHeading("h2"),
  h3: makeHeading("h3"),
  h4: makeHeading("h4"),
  h5: makeHeading("h5"),
  h6: makeHeading("h6"),
  code: ({ className, children, node: _node, ...rest }) => (
    <code
      className={`rounded bg-muted-foreground/10 px-1.5 py-0.5 font-mono text-[0.9em] ${className ?? ""}`}
      {...rest}
    >
      {children}
    </code>
  ),
  pre: ({ children, node: _node, ...rest }) => (
    <pre
      className="overflow-x-auto rounded-md border border-border bg-muted-foreground/5 p-4 font-mono text-sm [&>code]:bg-transparent [&>code]:p-0"
      {...rest}
    >
      {children}
    </pre>
  ),
  table: ({ children, node: _node, ...rest }) => (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm" {...rest}>
        {children}
      </table>
    </div>
  ),
  th: ({ children, node: _node, ...rest }) => (
    <th className="border-b border-border px-3 py-2 text-left font-semibold" {...rest}>
      {children}
    </th>
  ),
  td: ({ children, node: _node, ...rest }) => (
    <td className="border-b border-border px-3 py-2" {...rest}>
      {children}
    </td>
  ),
  blockquote: ({ children, node: _node, ...rest }) => (
    <blockquote
      className="border-l-4 border-accent/50 pl-4 text-muted-foreground italic"
      {...rest}
    >
      {children}
    </blockquote>
  ),
  u: makePlainInline("u"),
  sup: makePlainInline("sup"),
  sub: makePlainInline("sub"),
  b: makePlainInline("b"),
  i: makePlainInline("i"),
  em: makePlainInline("em"),
  strong: makePlainInline("strong"),
  br: Break,
};

// rehype-sanitize's GitHub-style default schema already allows the GFM
// elements this app relies on (headings, tables, links, lists, code,
// del/ins, task-list checkboxes) plus `sup`/`sub`/`b`/`i`/`em`/`strong`/`br`
// — but not `u`, and it still allows `img`. This app never serves images out
// of extracted/generated markdown, and `img` is a needless XSS/tracking
// vector (an attacker-controlled `src` still loads even once `onerror` is
// stripped), so it's the one tag explicitly removed here; `u` is the one
// tag explicitly added, for pymupdf4llm's `<u>` (stacked-fraction
// underlines). `script`/`iframe` are already excluded by the default schema
// (script's content is dropped too, not just unwrapped) and `javascript:`
// hrefs are already rejected by the default `protocols.href` allowlist —
// covered by this component's test suite rather than re-implemented here.
const schema = {
  ...defaultSchema,
  tagNames: [...(defaultSchema.tagNames ?? []).filter((tagName) => tagName !== "img"), "u"],
  attributes: Object.fromEntries(
    Object.entries(defaultSchema.attributes ?? {}).filter(([tagName]) => tagName !== "img"),
  ),
};

export interface MarkdownProps {
  children: string;
}

/**
 * remark-gfm adds GFM tables/strikethrough/task-lists. The extracted PDF
 * text legitimately contains inline HTML pymupdf4llm emits for stacked
 * fractions/superscripts (`<sup>`, `<sub>`, `<u>`); rehype-raw parses that
 * literal HTML into the hast tree (without it, react-markdown escapes any
 * HTML tag to plain text — which used to be this component's only defense,
 * and is why those tags used to render as literal "<sup><u>...</u></sup>"
 * text). rehype-sanitize then immediately filters the whole tree down to
 * `schema` below, so nothing else in that untrusted source (script, iframe,
 * img, event-handler attributes, javascript: URLs) survives either.
 * rehype-slug (heading ids for deep links) runs LAST, after sanitize:
 * sanitize's default schema clobber-prefixes any `id` it processes with
 * `user-content-` (GitHub's DOM-clobbering guard). Running slug first would
 * mean sanitize immediately rewrites the ids slug just added
 * ("hello-world" -> "user-content-hello-world"), breaking the `#hello-world`
 * anchors `makeHeading` builds from that same `id` prop.
 */
export default function Markdown({ children }: MarkdownProps) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeRaw, [rehypeSanitize, schema], rehypeSlug]}
      components={components}
    >
      {children}
    </ReactMarkdown>
  );
}
