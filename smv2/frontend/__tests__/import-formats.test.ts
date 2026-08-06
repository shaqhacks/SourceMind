import { describe, expect, it } from "vitest";

import {
  getImportFileDecision,
  IMPORT_ACCEPT_ATTRIBUTE,
  IMPORT_PICKER_ARIA_LABEL,
} from "@/lib/importFormats";

function file(name: string, type = ""): File {
  return new File(["content"], name, { type });
}

describe("import format policy", () => {
  it("accepts the stable student import formats by extension and MIME hint", () => {
    expect(getImportFileDecision(file("paper.pdf", "application/pdf")).status).toBe("supported");
    expect(getImportFileDecision(file("notes.md", "text/markdown")).status).toBe("supported");
    expect(getImportFileDecision(file("plain.txt", "text/plain")).status).toBe("supported");
    expect(getImportFileDecision(file("export.html", "text/html")).status).toBe("supported");
    expect(getImportFileDecision(file("README.MARKDOWN")).status).toBe("supported");
  });

  it("keeps archive formats visible as blocked with actionable not-yet-supported copy", () => {
    expect(getImportFileDecision(file("slides.pptx")).status).toBe("blocked");
    const epubDecision = getImportFileDecision(file("book.epub"));
    const docxDecision = getImportFileDecision(file("packet.docx"));
    expect(epubDecision.status).toBe("blocked");
    expect(docxDecision.status).toBe("blocked");
    if (epubDecision.status === "supported" || docxDecision.status === "supported") {
      throw new Error("archive formats must not be supported");
    }
    expect(epubDecision.message).toMatch(/not supported yet/i);
    expect(docxDecision.message).toMatch(/pdf, markdown, text, or html/i);
  });

  it("blocks archive extensions before supported MIME hints can spoof them", () => {
    const docxDecision = getImportFileDecision(file("packet.docx", "text/plain"));
    const pptxDecision = getImportFileDecision(file("slides.pptx", "text/html"));
    const epubDecision = getImportFileDecision(file("book.epub", "text/plain"));

    expect(docxDecision.status).toBe("blocked");
    expect(pptxDecision.status).toBe("blocked");
    expect(epubDecision.status).toBe("blocked");
    if (
      docxDecision.status === "supported" ||
      pptxDecision.status === "supported" ||
      epubDecision.status === "supported"
    ) {
      throw new Error("archive formats must stay blocked when MIME hints are text-like");
    }
    expect(docxDecision.message).toMatch(/not supported yet/i);
    expect(pptxDecision.message).toMatch(/not supported yet/i);
    expect(epubDecision.message).toMatch(/not supported yet/i);
  });

  it("exports one picker contract for every import entry point", () => {
    expect(IMPORT_ACCEPT_ATTRIBUTE).toBe(
      ".pdf,.md,.markdown,.txt,.text,.html,.htm,application/pdf,text/markdown,text/plain,text/html",
    );
    expect(IMPORT_PICKER_ARIA_LABEL).toBe("Upload course files");
  });
});
