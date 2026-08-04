import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import CompetencyDetailView from "@/components/skills/CompetencyDetailView";
import { getCourse, getSkillDetail, type CourseOut, type SkillDetailOut } from "@/lib/api/client";

import { err, ok } from "./support/api-result";

vi.mock("@/lib/api/client", () => ({
  getCourse: vi.fn(),
  getSkillDetail: vi.fn(),
}));

const mockedGetCourse = vi.mocked(getCourse);
const mockedGetSkillDetail = vi.mocked(getSkillDetail);

function makeCourse(overrides: Partial<CourseOut> = {}): CourseOut {
  return {
    id: "course-1",
    title: "Prompt Engineering Basics",
    status: "ready",
    section_count: 4,
    failed_asset_count: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    progress: null,
    ...overrides,
  };
}

function makeDetail(overrides: Partial<SkillDetailOut> = {}): SkillDetailOut {
  return {
    node: {
      id: "token-counting",
      slug: "token-counting",
      label: "Token counting",
      level: 1,
      status: "likely_struggling",
      readiness_estimate: 0.31,
      evidence_state: "likely_struggling",
      distinct_item_count: 5,
      distinct_session_count: 3,
      effective_evidence_count: 4.2,
      uncertainty: 0.18,
      quiz_estimate: 0.4,
      review_estimate: 0.25,
      trend: "declining",
      forgetting_risk: 0.2,
      last_evidence_at: "2026-01-02T00:00:00Z",
    },
    taught_in: [
      {
        section_id: "sec-2",
        chapter_label: "Chapter 2",
        title: "Counting and budgeting tokens",
        rank: 0,
        relevance_md: "Counting rules, context windows, and budget math.",
      },
      {
        section_id: "sec-1",
        chapter_label: "Chapter 1",
        title: "How text becomes tokens",
        rank: 1,
        relevance_md: "Where token boundaries come from.",
      },
    ],
    missed_questions: [
      {
        question: "A 3,000-word document is roughly how many tokens?",
        your_answer: "~1,500 tokens",
        correct_answer: "~4,000 tokens",
        source_test_id: "test-1",
        attempted_at: "2026-01-01T00:00:00Z",
      },
      {
        question: "Which change reduces token count the most?",
        your_answer: null,
        correct_answer: "Removing repeated boilerplate",
        source_test_id: "test-1",
        attempted_at: "2026-01-02T00:00:00Z",
      },
    ],
    cards_count: 5,
    quiz_correct: 2,
    quiz_wrong: 3,
    ...overrides,
  };
}

describe("CompetencyDetailView", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders readiness evidence, taught-in sections, and missed questions", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));
    mockedGetSkillDetail.mockResolvedValue(ok(makeDetail()));

    render(<CompetencyDetailView courseId="course-1" skillId="token-counting" />);

    expect(await screen.findByRole("heading", { level: 1, name: "Token counting" })).toBeInTheDocument();
    expect(screen.getByText("Likely struggling · 31% readiness")).toBeInTheDocument();

    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("Distinct evidence items")).toBeInTheDocument();
    expect(screen.getByText("Why this estimate")).toBeInTheDocument();
    expect(screen.getByText("40%")).toBeInTheDocument();
    expect(screen.getByText("25%")).toBeInTheDocument();
    expect(screen.getByText("2/5")).toBeInTheDocument();
    expect(screen.getByText("Quiz record")).toBeInTheDocument();

    // taughtIn: two sections, first tagged "Most relevant" and re-reads into the reader
    expect(screen.getByText("Counting and budgeting tokens")).toBeInTheDocument();
    expect(screen.getByText("How text becomes tokens")).toBeInTheDocument();
    expect(screen.getByText("Most relevant")).toBeInTheDocument();
    // Each Re-read link deep-links into the reader at the section it's
    // taught in (?section=<id>), not just the bare course — taughtIn order
    // above is sec-2 then sec-1.
    const reReadLinks = screen.getAllByRole("link", { name: "Re-read" });
    expect(reReadLinks.length).toBe(2);
    expect(reReadLinks[0]).toHaveAttribute("href", "/course/course-1?section=sec-2");
    expect(reReadLinks[1]).toHaveAttribute("href", "/course/course-1?section=sec-1");

    // Two missed questions, one with a null your_answer rendered as "Skipped"
    expect(screen.getByText(/3,000-word document/)).toBeInTheDocument();
    expect(screen.getByText(/reduces token count the most/)).toBeInTheDocument();
    expect(screen.getByText("You answered: Skipped")).toBeInTheDocument();
    expect(screen.getByText("You answered: ~1,500 tokens")).toBeInTheDocument();

    // The next step points to reviewed source material rather than asserting a cause.
    const startWith = screen.getByRole("link", { name: "Start with Counting and budgeting tokens" });
    expect(startWith).toHaveAttribute("href", "/course/course-1?section=sec-2");
    const practice = screen.getByRole("link", { name: "Practice and review" });
    expect(practice).toHaveAttribute("href", "/review?course=course-1");
  });

  it("shows a quiet note instead of fabricating missed questions for a skill with none", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));
    mockedGetSkillDetail.mockResolvedValue(
      ok(
        makeDetail({
          node: {
            id: "tokenization",
            slug: "tokenization",
            label: "Tokenization basics",
            level: 1,
            status: "retained",
            readiness_estimate: 0.86,
            evidence_state: "retained",
            distinct_item_count: 7,
          },
          missed_questions: [],
        }),
      ),
    );

    render(<CompetencyDetailView courseId="course-1" skillId="tokenization" />);

    expect(await screen.findByRole("heading", { level: 1, name: "Tokenization basics" })).toBeInTheDocument();
    expect(
      screen.getByText("No missed questions recorded for this skill yet."),
    ).toBeInTheDocument();
  });

  it("does not present a causal explanation for a low readiness estimate", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));
    mockedGetSkillDetail.mockResolvedValue(
      ok(
        makeDetail({
          node: {
            id: "cost-estimation",
            slug: "cost-estimation",
            label: "Cost estimation",
            level: 2,
            status: "likely_struggling",
            readiness_estimate: 0.24,
            evidence_state: "likely_struggling",
            distinct_item_count: 6,
          },
        }),
      ),
    );

    render(<CompetencyDetailView courseId="course-1" skillId="cost-estimation" />);

    await screen.findByRole("heading", { level: 1, name: "Cost estimation" });
    expect(screen.getByText("Next study step")).toBeInTheDocument();
    expect(screen.queryByText(/blocked by|fix that first/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /fix token counting/i })).not.toBeInTheDocument();
  });

  it("shows a not-linked note when a skill has no taught-in sections", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));
    mockedGetSkillDetail.mockResolvedValue(ok(makeDetail({ taught_in: [] })));

    render(<CompetencyDetailView courseId="course-1" skillId="token-counting" />);

    await screen.findByRole("heading", { level: 1, name: "Token counting" });
    expect(screen.getByText("Not linked to any section yet.")).toBeInTheDocument();
  });

  it("renders an EmptyState linking back to the skill map for an unknown skill id", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));
    mockedGetSkillDetail.mockResolvedValue(err(404));

    render(<CompetencyDetailView courseId="course-1" skillId="does-not-exist" />);

    expect(await screen.findByText("Skill not found")).toBeInTheDocument();
    const backLink = screen.getByRole("link", { name: "Back to the skill map" });
    expect(backLink).toHaveAttribute("href", "/course/course-1/skills");
  });

  it("shows a retryable error banner when the course fails to load", async () => {
    mockedGetCourse.mockResolvedValue(err(500));
    mockedGetSkillDetail.mockResolvedValue(ok(makeDetail()));

    render(<CompetencyDetailView courseId="course-1" skillId="token-counting" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Loading course failed");
    await waitFor(() => expect(mockedGetCourse).toHaveBeenCalledTimes(1));
  });

  it("shows a retryable error banner when the skill detail fails to load", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));
    mockedGetSkillDetail.mockResolvedValue(err(500));

    render(<CompetencyDetailView courseId="course-1" skillId="token-counting" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Loading skill failed");
  });
});
