import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import CompetencyDetailView from "@/components/skills/CompetencyDetailView";
import { getCourse, type CourseOut } from "@/lib/api/client";
import { SAMPLE_DATA_LABEL } from "@/lib/skills/placeholder";

import { err, ok } from "./support/api-result";

vi.mock("@/lib/api/client", () => ({
  getCourse: vi.fn(),
}));

const mockedGetCourse = vi.mocked(getCourse);

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

describe("CompetencyDetailView", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders the skill's status, blocked skills, taught-in sections, and missed questions", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));

    render(<CompetencyDetailView courseId="course-1" skillId="token-counting" />);

    expect(await screen.findByRole("heading", { level: 1, name: "Token counting" })).toBeInTheDocument();
    expect(screen.getByText("Struggling · 31 mastery")).toBeInTheDocument();
    expect(screen.getByText(SAMPLE_DATA_LABEL)).toBeInTheDocument();

    // blockedBy("token-counting") = [cost-estimation, context-management]
    expect(screen.getByText(/Blocks/)).toBeInTheDocument();
    expect(screen.getByText("Cost estimation and Context management")).toBeInTheDocument();

    // taughtIn: two sections, first tagged "Most relevant" and re-reads into the reader
    expect(screen.getByText("Counting and budgeting tokens")).toBeInTheDocument();
    expect(screen.getByText("How text becomes tokens")).toBeInTheDocument();
    expect(screen.getByText("Most relevant")).toBeInTheDocument();
    const reReadLinks = screen.getAllByRole("link", { name: "Re-read" });
    expect(reReadLinks.length).toBe(2);
    reReadLinks.forEach((link) => expect(link).toHaveAttribute("href", "/course/course-1"));

    // MISSED_QUESTIONS["token-counting"] has two entries
    expect(screen.getByText(/3,000-word document/)).toBeInTheDocument();
    expect(screen.getByText(/reduces token count the most/)).toBeInTheDocument();

    // Fix plan CTAs
    const startWith = screen.getByRole("link", { name: "Start with Counting and budgeting tokens" });
    expect(startWith).toHaveAttribute("href", "/course/course-1");
    const drillCards = screen.getByRole("link", { name: "Drill cards" });
    expect(drillCards).toHaveAttribute("href", "/review");
  });

  it("shows a quiet note instead of fabricating missed questions for a skill with none", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));

    render(<CompetencyDetailView courseId="course-1" skillId="tokenization" />);

    expect(await screen.findByRole("heading", { level: 1, name: "Tokenization basics" })).toBeInTheDocument();
    expect(
      screen.getByText("No missed questions recorded for this skill yet."),
    ).toBeInTheDocument();
  });

  it("renders an EmptyState linking back to the skill map for an unknown skill id", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));

    render(<CompetencyDetailView courseId="course-1" skillId="does-not-exist" />);

    expect(await screen.findByText("Skill not found")).toBeInTheDocument();
    const backLink = screen.getByRole("link", { name: "Back to the skill map" });
    expect(backLink).toHaveAttribute("href", "/course/course-1/skills");
  });

  it("shows a retryable error banner when the course fails to load", async () => {
    mockedGetCourse.mockResolvedValue(err(500));

    render(<CompetencyDetailView courseId="course-1" skillId="token-counting" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Loading course failed");
    await waitFor(() => expect(mockedGetCourse).toHaveBeenCalledTimes(1));
  });
});
