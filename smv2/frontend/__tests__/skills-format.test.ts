import { describe, expect, it } from "vitest";

import { joinNames } from "@/components/skills/format";

describe("joinNames", () => {
  it("returns an empty string for an empty list", () => {
    expect(joinNames([])).toBe("");
  });

  it("returns the bare name for a single-item list", () => {
    expect(joinNames(["A"])).toBe("A");
  });

  it("joins two names with 'and', no comma", () => {
    expect(joinNames(["A", "B"])).toBe("A and B");
  });

  it("joins three or more names with an Oxford comma before 'and'", () => {
    expect(joinNames(["A", "B", "C"])).toBe("A, B, and C");
  });
});
