"use client";

import type { ComponentPropsWithoutRef } from "react";
import ReactMarkdown, { type Components, type ExtraProps } from "react-markdown";
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
};

export interface MarkdownProps {
  children: string;
}

/**
 * remark-gfm adds GFM tables/strikethrough/task-lists; rehype-slug adds
 * deep-linkable heading ids. Deliberately NOT using rehype-raw: the source
 * text this renders is extracted from untrusted PDFs, and without
 * rehype-raw, react-markdown treats any literal HTML tags in the markdown
 * as plain escaped text rather than rendering them. Do not add rehype-raw.
 */
export default function Markdown({ children }: MarkdownProps) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSlug]} components={components}>
      {children}
    </ReactMarkdown>
  );
}
