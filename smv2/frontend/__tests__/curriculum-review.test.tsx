import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import CurriculumReview from "@/components/curriculum/CurriculumReview";
import {
  editCurriculumConcept,
  getCurriculum,
  listEvidenceMappings,
  reviewEvidenceMapping,
  type CurriculumVersionOut,
} from "@/lib/api/client";

import { ok } from "./support/api-result";

vi.mock("@/lib/api/client", () => ({
  createCurriculumDraft: vi.fn(),
  editCurriculumClaim: vi.fn(),
  editCurriculumConcept: vi.fn(),
  getCurriculum: vi.fn(),
  listEvidenceMappings: vi.fn(),
  publishCurriculum: vi.fn(),
  reviewEvidenceMapping: vi.fn(),
}));

const curriculum: CurriculumVersionOut = {
  id: "version-1",
  course_id: "course-1",
  parent_version_id: null,
  status: "draft",
  is_current: false,
  label: "Review draft",
  created_at: "2026-01-01T00:00:00Z",
  published_at: null,
  concepts: [{ id: "concept-1", stable_key: "fractions", label: "Fractions", description_md: "Compare fractions.", aliases: [], chapter_label: "Chapter 1", section_id: null, section_title: null, review_state: "unverified", is_active: true }],
  claims: [{ id: "claim-1", stable_key: "compare", concept_id: "concept-1", statement: "Compare two fractions.", success_criteria_md: "Chooses and explains.", aliases: [], cognitive_demand: "apply", review_state: "unverified", is_active: true }],
  relations: [],
  sources: [],
};

describe("CurriculumReview", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("edits a draft and reviews item mappings without rewriting the published version", async () => {
    vi.mocked(getCurriculum).mockResolvedValue(ok(curriculum));
    vi.mocked(listEvidenceMappings).mockResolvedValue(ok([{
      id: "mapping-1",
      evidence_item_id: "item-1",
      item_type: "practice_question",
      item_preview: "Which fraction is larger?",
      concept_id: "concept-1",
      concept_label: "Fractions",
      learning_claim_id: "claim-1",
      claim_statement: "Compare two fractions.",
      role: "primary",
      task_type: "multiple_choice",
      cognitive_demand: "apply",
      mapping_confidence: 0.81,
      review_state: "unverified",
      source_ref: "Chapter 1 example",
    }]));
    vi.mocked(editCurriculumConcept).mockResolvedValue(ok({ concept_id: "concept-1" }));
    vi.mocked(reviewEvidenceMapping).mockResolvedValue(ok({} as never));
    const user = userEvent.setup();

    render(<CurriculumReview courseId="course-1" />);

    const label = await screen.findByLabelText("Concept label Fractions");
    await user.clear(label);
    await user.type(label, "Fraction comparison");
    await user.click(screen.getByRole("button", { name: "Save concept" }));
    expect(editCurriculumConcept).toHaveBeenCalledWith(
      "version-1",
      "concept-1",
      expect.objectContaining({ label: "Fraction comparison" }),
    );

    await user.click(screen.getByRole("button", { name: "Verify mapping" }));
    expect(reviewEvidenceMapping).toHaveBeenCalledWith("mapping-1", "verified");
  });
});
