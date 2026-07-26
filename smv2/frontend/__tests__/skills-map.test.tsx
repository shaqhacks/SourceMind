import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import SkillMapView from "@/components/skills/SkillMapView";
import { getCourse, type CourseOut } from "@/lib/api/client";
import { SAMPLE_DATA_LABEL, SKILL_NODES } from "@/lib/skills/placeholder";

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

describe("SkillMapView", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders every sample skill as a card linking to its detail page, tagged as sample data", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));

    render(<SkillMapView courseId="course-1" />);

    expect(await screen.findByText("Skill map — Prompt Engineering Basics")).toBeInTheDocument();
    expect(screen.getByText(SAMPLE_DATA_LABEL)).toBeInTheDocument();

    for (const node of SKILL_NODES) {
      // getAllByText (not getByText): the root-cause skill's name also
      // appears a second time in the "Recommended fix" prose below.
      expect(screen.getAllByText(node.name).length).toBeGreaterThan(0);
    }

    // A struggling skill's whole card is a link to its competency page.
    const strugglingLink = screen.getByRole("link", { name: /Token counting/ });
    expect(strugglingLink).toHaveAttribute("href", "/course/course-1/skills/token-counting");
  });

  it("shows the legend and the data-driven recommended fix card", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));

    render(<SkillMapView courseId="course-1" />);
    await screen.findByText("Skill map — Prompt Engineering Basics");

    expect(screen.getByText("prerequisite met")).toBeInTheDocument();
    expect(screen.getByText("weak prerequisite — fix first")).toBeInTheDocument();

    expect(screen.getByText("Recommended fix")).toBeInTheDocument();
    const startFix = screen.getByRole("link", { name: "Start 4-min fix" });
    // rootCause() resolves to { skill: cost-estimation, prereq: token-counting }
    // for this dataset — the fix points at the weak prereq's own detail page.
    expect(startFix).toHaveAttribute("href", "/course/course-1/skills/token-counting");
  });

  it("disables the By chapter toggle with an explanatory title", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));

    render(<SkillMapView courseId="course-1" />);
    await screen.findByText("Skill map — Prompt Engineering Basics");

    const byChapter = screen.getByRole("button", { name: "By chapter" });
    expect(byChapter).toBeDisabled();
    expect(byChapter).toHaveAttribute("title", "Coming with the competency backend");
  });

  it("shows a retryable error banner when the course fails to load", async () => {
    mockedGetCourse.mockResolvedValue(err(500));

    render(<SkillMapView courseId="course-1" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Loading course failed");
    await waitFor(() => expect(mockedGetCourse).toHaveBeenCalledTimes(1));
  });
});
