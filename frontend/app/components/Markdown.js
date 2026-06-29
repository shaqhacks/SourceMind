"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeRaw from "rehype-raw";
import rehypeKatex from "rehype-katex";
import rehypeHighlight from "rehype-highlight";
import { API_URL } from "../lib/api";
import Quiz from "./Quiz";

// ---------------------------------------------------------------------------
// Custom component overrides
// ---------------------------------------------------------------------------

/** Prefix backend-relative image paths with API_URL. */
function Img({ src, alt, ...props }) {
  const resolved = src && src.startsWith("/") ? `${API_URL}${src}` : src;
  return (
    <img
      src={resolved}
      alt={alt || ""}
      style={{
        maxWidth: "100%",
        height: "auto",
        borderRadius: 8,
        display: "block",
        margin: "1.5em auto",
      }}
      {...props}
    />
  );
}

/**
 * Pre wrapper — inspects its child <code> element BEFORE it renders.
 * If the code block has `language-quiz`, renders a transparent div so the
 * Quiz component (returned by the Code override below) isn't constrained by
 * <pre> whitespace/scroll behaviour.
 */
function Pre({ children }) {
  const child = Array.isArray(children) ? children[0] : children;
  const isQuiz =
    child &&
    child.props &&
    child.props.className === "language-quiz";

  if (isQuiz) {
    return <div>{children}</div>;
  }

  return (
    <pre
      style={{
        background: "#0e1422",
        border: "1px solid var(--border)",
        borderRadius: 8,
        padding: "14px 18px",
        overflowX: "auto",
        fontSize: 13,
        lineHeight: 1.65,
        margin: "1.5em 0",
      }}
    >
      {children}
    </pre>
  );
}

/**
 * Code renderer — intercepts `quiz` fenced blocks and renders <Quiz>.
 * Falls back to styled inline/block code for everything else.
 */
function Code({ className, children, ...props }) {
  // Fenced block with info-string `quiz`
  if (className === "language-quiz") {
    try {
      const items = JSON.parse(String(children).trim());
      return <Quiz items={Array.isArray(items) ? items : []} />;
    } catch {
      // JSON parse failed — fall through to raw code display
    }
  }

  // Regular inline or block code
  return (
    <code
      className={className}
      style={{
        background: "#0e1422",
        border: "1px solid var(--border)",
        borderRadius: 4,
        padding: className ? 0 : "2px 6px",  // 0 padding inside <pre>
        fontSize: "0.88em",
        fontFamily: "ui-monospace, SFMono-Regular, Consolas, monospace",
        color: "#c9d1d9",
      }}
      {...props}
    >
      {children}
    </code>
  );
}

/** Blockquote — styled distinctively for > ✏️ Try it: boxes. */
function Blockquote({ children }) {
  return (
    <blockquote
      style={{
        margin: "1.5em 0",
        padding: "12px 20px",
        borderLeft: "4px solid var(--accent)",
        background: "rgba(91,140,255,0.06)",
        borderRadius: "0 8px 8px 0",
        color: "var(--text)",
      }}
    >
      {children}
    </blockquote>
  );
}

/** Table — full-width with border grid. */
function Table({ children }) {
  return (
    <div style={{ overflowX: "auto", margin: "1.5em 0" }}>
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontSize: 14,
          lineHeight: 1.5,
        }}
      >
        {children}
      </table>
    </div>
  );
}

function Th({ children, style: _s, ...props }) {
  return (
    <th
      style={{
        padding: "8px 14px",
        borderBottom: "2px solid var(--border)",
        textAlign: "left",
        fontSize: 13,
        fontWeight: 700,
        color: "var(--muted)",
        textTransform: "uppercase",
        letterSpacing: "0.04em",
        background: "#0e1422",
      }}
      {...props}
    >
      {children}
    </th>
  );
}

function Td({ children, style: _s, ...props }) {
  return (
    <td
      style={{
        padding: "8px 14px",
        borderBottom: "1px solid var(--border)",
      }}
      {...props}
    >
      {children}
    </td>
  );
}

/** Headings — descending size with accent left-border on h2. */
const headingStyle = (level) => {
  const sizes = { 1: 28, 2: 22, 3: 18, 4: 16, 5: 15, 6: 14 };
  return {
    fontSize: sizes[level] || 16,
    fontWeight: level <= 2 ? 700 : 600,
    lineHeight: 1.3,
    marginTop: level === 1 ? "0.5em" : "2em",
    marginBottom: "0.6em",
    ...(level === 2
      ? {
          paddingBottom: "0.3em",
          borderBottom: "1px solid var(--border)",
        }
      : {}),
  };
};

const H1 = ({ children }) => <h1 style={headingStyle(1)}>{children}</h1>;
const H2 = ({ children }) => <h2 style={headingStyle(2)}>{children}</h2>;
const H3 = ({ children }) => <h3 style={headingStyle(3)}>{children}</h3>;
const H4 = ({ children }) => <h4 style={headingStyle(4)}>{children}</h4>;
const H5 = ({ children }) => <h5 style={headingStyle(5)}>{children}</h5>;
const H6 = ({ children }) => <h6 style={headingStyle(6)}>{children}</h6>;

// ---------------------------------------------------------------------------
// Component map
// ---------------------------------------------------------------------------

const COMPONENTS = {
  img: Img,
  pre: Pre,
  code: Code,
  blockquote: Blockquote,
  table: Table,
  th: Th,
  td: Td,
  h1: H1,
  h2: H2,
  h3: H3,
  h4: H4,
  h5: H5,
  h6: H6,
};

// ---------------------------------------------------------------------------
// Markdown — main export
// ---------------------------------------------------------------------------

/**
 * Renders chapter `body_md` with full GFM support, quiz-fence interception,
 * backend-relative image resolution, and styled prose.
 *
 * Props
 *   source: string  — the raw markdown text (body_md from a chapter)
 */
export default function Markdown({ source = "" }) {
  return (
    <div
      style={{
        // Comfortable reading column
        maxWidth: "72ch",
        lineHeight: 1.8,
        fontSize: 16,
        color: "var(--text)",
        // Vertical rhythm for bare p/ul/ol/li
      }}
    >
      <style>{`
        .md-prose p { margin: 0 0 1.1em; }
        .md-prose ul, .md-prose ol { margin: 0 0 1.1em 1.6em; padding: 0; }
        .md-prose li { margin-bottom: 0.35em; line-height: 1.7; }
        .md-prose li > p { margin: 0; }
        .md-prose hr { border: none; border-top: 1px solid var(--border); margin: 2em 0; }
        .md-prose a { color: var(--accent); }
        .md-prose a:hover { text-decoration: underline; }
        .md-prose details { margin: 1.2em 0; }
        .md-prose summary {
          cursor: pointer;
          font-weight: 600;
          color: var(--accent);
          padding: 6px 0;
          list-style: none;
        }
        .md-prose summary::-webkit-details-marker { display: none; }
        .md-prose summary::before {
          content: "▶ ";
          font-size: 0.75em;
          color: var(--muted);
        }
        .md-prose details[open] > summary::before { content: "▼ "; }
        .md-prose details > :not(summary) { margin-top: 8px; }
        .md-prose strong { font-weight: 700; }
        .md-prose em { font-style: italic; }
        .md-prose del { opacity: 0.55; text-decoration: line-through; }
      `}</style>
      <div className="md-prose">
        <ReactMarkdown
          remarkPlugins={[remarkMath, remarkGfm]}
          rehypePlugins={[rehypeRaw, rehypeKatex, [rehypeHighlight, { ignoreMissing: true }]]}
          components={COMPONENTS}
        >
          {source}
        </ReactMarkdown>
      </div>
    </div>
  );
}
