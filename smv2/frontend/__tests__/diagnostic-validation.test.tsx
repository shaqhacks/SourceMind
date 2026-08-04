import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import DiagnosticValidation from "@/components/diagnostics/DiagnosticValidation";
import {
  getDiagnosticValidationSummary,
  getNextDiagnosticValidation,
  submitDiagnosticJudgment,
} from "@/lib/api/client";

import { ok } from "./support/api-result";

vi.mock("@/lib/api/client", () => ({
  getDiagnosticValidationSummary: vi.fn(),
  getNextDiagnosticValidation: vi.fn(),
  submitDiagnosticJudgment: vi.fn(),
}));

describe("DiagnosticValidation", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("keeps the model result blinded until the instructor records a judgment", async () => {
    vi.mocked(getNextDiagnosticValidation).mockResolvedValue(ok({
      concept_id: "concept-1",
      concept_label: "Fractions",
      concept_description_md: "Compare and represent fractions.",
      evidence_available: true,
    }));
    vi.mocked(getDiagnosticValidationSummary).mockResolvedValue(ok({
      sample_size: 0,
      agreement_count: 0,
      pending_reason_count: 0,
      raw_agreement: null,
      chance_adjusted_agreement: null,
      sufficient_sample: false,
      disagreement_reasons: {},
      disagreements_by_concept: {},
    }));
    vi.mocked(submitDiagnosticJudgment).mockResolvedValue(ok({
      id: "judgment-1",
      concept_id: "concept-1",
      judgment: "likely_struggling",
      disagreement_reason: null,
      model_state: "likely_struggling",
      readiness_estimate: 0.28,
      evidence_count: 5,
      model_version: "transparent-beta-v1",
      agreement: true,
      requires_disagreement_reason: false,
      created_at: "2026-01-01T00:00:00Z",
    }));
    const user = userEvent.setup();

    render(<DiagnosticValidation courseId="course-1" />);

    expect(await screen.findByText("Fractions")).toBeInTheDocument();
    expect(screen.queryByText(/28%/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Likely struggling" }));

    expect(submitDiagnosticJudgment).toHaveBeenCalledWith("course-1", {
      concept_id: "concept-1",
      judgment: "likely_struggling",
      disagreement_reason: null,
      notes_md: null,
    });
    expect(await screen.findByText(/28% readiness/i)).toBeInTheDocument();
    expect(screen.getByText(/agrees with your judgment/i)).toBeInTheDocument();
  });
});
