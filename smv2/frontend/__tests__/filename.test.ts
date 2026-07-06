import { describe, expect, it } from "vitest";

import { defaultTitleFromFilename } from "@/lib/upload/filename";

describe("defaultTitleFromFilename", () => {
  it("strips the extension and turns underscores/hyphens into spaces", () => {
    expect(defaultTitleFromFilename("intro_to-testing.pdf")).toBe("intro to testing");
  });

  it("collapses repeated separators", () => {
    expect(defaultTitleFromFilename("chapter__1--notes.pdf")).toBe("chapter 1 notes");
  });

  it("trims leading/trailing separators left over after stripping the extension", () => {
    expect(defaultTitleFromFilename("_draft_.pdf")).toBe("draft");
  });

  it("falls back to 'Untitled course' when nothing meaningful is left", () => {
    expect(defaultTitleFromFilename(".pdf")).toBe("Untitled course");
    expect(defaultTitleFromFilename("___.pdf")).toBe("Untitled course");
  });

  it("only strips the final extension, not dots inside the name", () => {
    expect(defaultTitleFromFilename("v2.final.draft.pdf")).toBe("v2.final.draft");
  });
});
