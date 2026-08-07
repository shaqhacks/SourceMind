import { describe, expect, it } from "vitest";

import config from "../vitest.config";

describe("vitest config", () => {
  it("keeps Playwright specs out of the unit-test suite", () => {
    expect(config.test?.exclude).toEqual(
      expect.arrayContaining(["e2e/**", "test-results/**"]),
    );
  });
});
