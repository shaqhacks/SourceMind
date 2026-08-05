export const IMPORT_PICKER_ARIA_LABEL = "Upload course files";

export const IMPORT_ACCEPT_ATTRIBUTE = [
  ".pdf",
  ".md",
  ".markdown",
  ".txt",
  ".text",
  ".html",
  ".htm",
  "application/pdf",
  "text/markdown",
  "text/plain",
  "text/html",
].join(",");

const SUPPORTED_EXTENSIONS = new Set(["pdf", "md", "markdown", "txt", "text", "html", "htm"]);
const SUPPORTED_MIME_TYPES = new Set([
  "application/pdf",
  "text/markdown",
  "text/plain",
  "text/html",
]);
const BLOCKED_EXTENSIONS = new Set(["docx", "pptx", "epub"]);

export type ImportFileDecision =
  | { status: "supported" }
  | { status: "blocked" | "unsupported"; message: string };

export const UNSUPPORTED_SOURCE_FORMAT_MESSAGE =
  "That file type is not supported yet. Upload PDF, Markdown, text, or HTML instead.";

function extensionOf(name: string): string {
  const lastSegment = name.split(/[\\/]/).pop() ?? name;
  const dot = lastSegment.lastIndexOf(".");
  return dot === -1 ? "" : lastSegment.slice(dot + 1).toLowerCase();
}

export function getImportFileDecision(file: File): ImportFileDecision {
  const extension = extensionOf(file.name);
  const mimeType = file.type.toLowerCase();

  if (SUPPORTED_EXTENSIONS.has(extension) || SUPPORTED_MIME_TYPES.has(mimeType)) {
    return { status: "supported" };
  }

  if (BLOCKED_EXTENSIONS.has(extension)) {
    return { status: "blocked", message: `${file.name}: ${UNSUPPORTED_SOURCE_FORMAT_MESSAGE}` };
  }

  return { status: "unsupported", message: `${file.name}: ${UNSUPPORTED_SOURCE_FORMAT_MESSAGE}` };
}

export function supportedImportFiles(files: FileList | File[]): File[] {
  return Array.from(files).filter((file) => getImportFileDecision(file).status === "supported");
}
