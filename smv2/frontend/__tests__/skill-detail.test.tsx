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
      mastery: 31,
      status: "struggling",
      blocked: false,
      unlock_note: null,
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
    blocked_skill_labels: ["Cost estimation", "Context management"],
    cards_count: 5,
    quiz_correct: 2,
    quiz_wrong: 3,
    fix_plan: null,
    ...overrides,
  };
}

describe("CompetencyDetailView", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders the skill's status, blocked skills, taught-in sections, and missed questions", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));
    mockedGetSkillDetail.mockResolvedValue(ok(makeDetail()));

    render(<CompetencyDetailView courseId="course-1" skillId="token-counting" />);

    expect(await screen.findByRole("heading", { level: 1, name: "Token counting" })).toBeInTheDocument();
    expect(screen.getByText("Struggling · 31 mastery")).toBeInTheDocument();

    expect(screen.getByText(/Blocks/)).toBeInTheDocument();
    expect(screen.getByText("Cost estimation and Context management")).toBeInTheDocument();

    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("Cards on this skill")).toBeInTheDocument();
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

    // fix_plan is null for this skill (its own prereq, tokenization, isn't
    // weak) — the fallback plan re-reads the top taught-in section.
    const startWith = screen.getByRole("link", { name: "Start with Counting and budgeting tokens" });
    expect(startWith).toHaveAttribute("href", "/course/course-1?section=sec-2");
    const drillCards = screen.getByRole("link", { name: "Drill cards" });
    expect(drillCards).toHaveAttribute("href", "/review");
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
            mastery: 86,
            status: "solid",
            blocked: false,
            unlock_note: null,
          },
          missed_questions: [],
          blocked_skill_labels: [],
        }),
      ),
    );

    render(<CompetencyDetailView courseId="course-1" skillId="tokenization" />);

    expect(await screen.findByRole("heading", { level: 1, name: "Tokenization basics" })).toBeInTheDocument();
    expect(
      screen.getByText("No missed questions recorded for this skill yet."),
    ).toBeInTheDocument();
  });

  it("shows a fix plan pointing at the weak prerequisite when fix_plan is present", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));
    mockedGetSkillDetail.mockResolvedValue(
      ok(
        makeDetail({
          node: {
            id: "cost-estimation",
            slug: "cost-estimation",
            label: "Cost estimation",
            level: 2,
            mastery: 24,
            status: "struggling",
            blocked: true,
            unlock_note: null,
          },
          fix_plan: { prereq_id: "token-counting", prereq_label: "Token counting", section_id: "sec-2" },
        }),
      ),
    );

    render(<CompetencyDetailView courseId="course-1" skillId="cost-estimation" />);

    await screen.findByRole("heading", { level: 1, name: "Cost estimation" });
    expect(
      screen.getByText(/blocked by weak Token counting\. Fix that first/i),
    ).toBeInTheDocument();
    const fixLink = screen.getByRole("link", { name: "Fix Token counting" });
    expect(fixLink).toHaveAttribute("href", "/course/course-1/skills/token-counting");
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
