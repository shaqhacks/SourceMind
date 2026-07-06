"use client";

import { isValidElement, type ComponentPropsWithoutRef, type ReactNode } from "react";
import ReactMarkdown, { type Components, type ExtraProps } from "react-markdown";
import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { buildCourseImageUrl } from "@/lib/api/client";

// KaTeX's own stylesheet — self-hosted from the npm package, no CDN. Needed
// wherever this component renders, so it's imported here once rather than
// in every page that uses Markdown; Next.js dedupes it regardless of how
// many times this module is imported.
import "katex/dist/katex.min.css";

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

// remark-math tags `$…$`/`$$…$$` as `<code class="language-math math-inline">`
// / `<pre><code class="language-math math-display">` (see the schema
// comment below); rehype-katex then replaces those elements' *contents*
// with its own rendered output but leaves the outer code/pre tag and
// className alone. Detected here so those two containers skip the regular
// code-block chrome (monospace font, gray box, border) that would otherwise
// visually clash with a typeset equation.
function isMathClassName(className: unknown): className is string {
  return (
    typeof className === "string" &&
    (className.includes("math-inline") || className.includes("math-display"))
  );
}

function findMathClassName(children: ReactNode): string | null {
  let found: string | null = null;
  for (const child of Array.isArray(children) ? children : [children]) {
    if (isValidElement<{ className?: string }>(child) && isMathClassName(child.props.className)) {
      found = child.props.className;
    }
  }
  return found;
}

// Extracted-image references the backend writes into body_md/generated
// content: `![alt](/api/courses/{course_id}/images/{filename})`. Gated at
// the component level, not the sanitize schema — see the schema comment
// below for why `img` has to stay structurally allowed there regardless.
const EXTRACTED_IMAGE_SRC = /^\/api\/courses\/([A-Za-z0-9-]+)\/images\/([A-Za-z0-9._-]+)$/;

function MarkdownImage({ src, alt, node: _node }: ComponentPropsWithoutRef<"img"> & ExtraProps) {
  const match = typeof src === "string" ? EXTRACTED_IMAGE_SRC.exec(src) : null;
  if (!match) {
    // Anything that isn't our own extracted-image path — an external
    // http(s) URL, a data: URI, or a raw-HTML <img> smuggled into the
    // untrusted extracted text — renders as nothing, the same outcome as
    // every other disallowed construct in this component.
    return null;
  }
  const [, courseId, filename] = match;
  return (
    // next/image requires build-time-known dimensions/loader config; these
    // are runtime, per-course, backend-served paths.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={buildCourseImageUrl(courseId, filename)}
      alt={alt ?? ""}
      loading="lazy"
      className="my-4 block h-auto max-w-full"
    />
  );
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
  code: ({ className, children, node: _node, ...rest }) => {
    if (isMathClassName(className)) {
      return (
        <code className={className} {...rest}>
          {children}
        </code>
      );
    }
    return (
      <code
        className={`rounded bg-muted-foreground/10 px-1.5 py-0.5 font-mono text-[0.9em] ${className ?? ""}`}
        {...rest}
      >
        {children}
      </code>
    );
  },
  pre: ({ children, node: _node, ...rest }) => {
    if (findMathClassName(children)) {
      // Not a spread of `rest` — its `ref`/other DOM props are typed for a
      // <pre>, not this <div> replacement, and none of them matter for a
      // pure chrome-avoidance wrapper.
      return <div className="overflow-x-auto">{children}</div>;
    }
    return (
      <pre
        className="overflow-x-auto rounded-md border border-border bg-muted-foreground/5 p-4 font-mono text-sm [&>code]:bg-transparent [&>code]:p-0"
        {...rest}
      >
        {children}
      </pre>
    );
  },
  img: MarkdownImage,
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
// del/ins, task-list checkboxes, `img`) plus `sup`/`sub`/`b`/`i`/`em`/
// `strong`/`br` — but not `u`. `script`/`iframe` are already excluded
// (script's content is dropped too, not just unwrapped) and `javascript:`
// hrefs are already rejected by the default `protocols.href` allowlist —
// covered by this component's test suite rather than re-implemented here.
//
// `img` stays structurally allowed here even though this app only ever
// wants to render its own extracted-image references: sanitize can't tell
// a markdown-native `![]()` image apart from a raw `<img>` smuggled into
// the untrusted extracted text (rehype-raw has already expanded both into
// identical hast `element` nodes by this point) — there is no schema-level
// way to allow one and not the other. The real gate is `MarkdownImage`
// above, which only ever renders a real `<img>` for a `src` matching this
// app's own `/api/courses/{id}/images/{file}` path; every other case
// (external http(s), `data:`, a raw-HTML `<img onerror>`) renders nothing,
// so in practice this achieves the same outcome as excluding the tag
// entirely — see __tests__/markdown.test.tsx's img-related cases.
//
// `code`'s className entry is extended for remark-math's output: it tags
// math with `language-math math-inline`/`math-display` classes on a `code`
// element (`language-math` alone already matches the default schema's
// `/^language-./` regex; the two -inline/-display suffixes need to be
// listed explicitly) — this is rehype-katex's own documented pattern for
// combining with rehype-sanitize (see its readme's Security section).
const schema = {
  ...defaultSchema,
  tagNames: [...(defaultSchema.tagNames ?? []), "u"],
  attributes: {
    ...defaultSchema.attributes,
    code: [["className", /^language-./, "math-inline", "math-display"]],
  },
};

export interface MarkdownProps {
  children: string;
}

/**
 * remark-gfm adds GFM tables/strikethrough/task-lists; remark-math tags
 * `$…$`/`$$…$$` as math nodes (generated lesson/chat/card/quiz content —
 * prompts v2 instructs the model to emit this syntax). The extracted PDF
 * text legitimately contains inline HTML pymupdf4llm emits for stacked
 * fractions/superscripts (`<sup>`, `<sub>`, `<u>`); rehype-raw parses that
 * literal HTML into the hast tree (without it, react-markdown escapes any
 * HTML tag to plain text — which used to be this component's only defense,
 * and is why those tags used to render as literal "<sup><u>...</u></sup>"
 * text). rehype-sanitize then immediately filters the whole tree down to
 * `schema` above, so nothing else in that untrusted source (script, iframe,
 * event-handler attributes, javascript: URLs) survives — `img`'s own gating
 * is handled at the component level, see the schema comment.
 *
 * rehype-katex runs AFTER sanitize, not before: it replaces the (now
 * sanitize-approved) `language-math` code elements with its real rendered
 * markup (nested spans, MathML, aria attributes), which sanitize would
 * otherwise strip if it ran afterward — this is rehype-katex's own
 * documented ordering. `trust: false` (KaTeX's own default, set explicitly
 * here) rejects `\href`/`\includegraphics`/`\htmlClass` etc. — commands
 * that could otherwise emit attacker-controlled HTML/URLs — rendering them
 * as an inline error instead of executing them.
 *
 * rehype-slug (heading ids for deep links) runs LAST, after sanitize:
 * sanitize's default schema clobber-prefixes any `id` it processes with
 * `user-content-` (GitHub's DOM-clobbering guard). Running slug first would
 * mean sanitize immediately rewrites the ids slug just added
 * ("hello-world" -> "user-content-hello-world"), breaking the `#hello-world`
 * anchors `makeHeading` builds from that same `id` prop. Katex's own output
 * has no heading ids to clobber, so its position relative to slug is
 * otherwise unconstrained.
 */
export default function Markdown({ children }: MarkdownProps) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[
        rehypeRaw,
        [rehypeSanitize, schema],
        [rehypeKatex, { trust: false, strict: "warn" }],
        rehypeSlug,
      ]}
      components={components}
    >
      {children}
    </ReactMarkdown>
  );
}
