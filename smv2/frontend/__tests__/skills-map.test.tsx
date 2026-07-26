import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import SkillMapView from "@/components/skills/SkillMapView";
import {
  getCourse,
  getSkillMap,
  type CourseOut,
  type SkillEdgeOut,
  type SkillMapOut,
  type SkillNodeOut,
} from "@/lib/api/client";

import { err, ok } from "./support/api-result";

vi.mock("@/lib/api/client", () => ({
  getCourse: vi.fn(),
  getSkillMap: vi.fn(),
}));

const mockedGetCourse = vi.mocked(getCourse);
const mockedGetSkillMap = vi.mocked(getSkillMap);

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

// Mirrors the design mock's 6-node graph: token-counting's own weakness
// (mastery 31) makes it a "weak" prereq source for cost-estimation and
// context-management, which is what makes those two blocked=true and
// makes cost-estimation ("struggling" + "blocked") the map's root cause.
const NODES: SkillNodeOut[] = [
  { id: "tokenization", slug: "tokenization", label: "Tokenization basics", level: 1, mastery: 86, status: "solid", blocked: false, unlock_note: null },
  { id: "token-counting", slug: "token-counting", label: "Token counting", level: 1, mastery: 31, status: "struggling", blocked: false, unlock_note: null },
  { id: "prompt-structure", slug: "prompt-structure", label: "Prompt structure", level: 1, mastery: 58, status: "growing", blocked: false, unlock_note: null },
  { id: "cost-estimation", slug: "cost-estimation", label: "Cost estimation", level: 2, mastery: 24, status: "struggling", blocked: true, unlock_note: null },
  { id: "context-management", slug: "context-management", label: "Context management", level: 2, mastery: 52, status: "growing", blocked: true, unlock_note: null },
  { id: "caching", slug: "caching", label: "Prompt caching", level: 3, mastery: 0, status: "locked", blocked: true, unlock_note: "Unlocks at 60 mastery of Cost estimation" },
];

const EDGES: SkillEdgeOut[] = [
  { from_id: "tokenization", to_id: "token-counting", kind: "met" },
  { from_id: "token-counting", to_id: "cost-estimation", kind: "weak" },
  { from_id: "token-counting", to_id: "context-management", kind: "weak" },
  { from_id: "prompt-structure", to_id: "context-management", kind: "weak" },
  { from_id: "cost-estimation", to_id: "caching", kind: "weak" },
  { from_id: "context-management", to_id: "caching", kind: "weak" },
];

function makeSkillMap(overrides: Partial<SkillMapOut> = {}): SkillMapOut {
  return { nodes: NODES, edges: EDGES, ...overrides };
}

describe("SkillMapView", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders every skill as a card linking to its detail page", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));
    mockedGetSkillMap.mockResolvedValue(ok(makeSkillMap()));

    render(<SkillMapView courseId="course-1" />);

    expect(await screen.findByText("Skill map — Prompt Engineering Basics")).toBeInTheDocument();

    for (const node of NODES) {
      // getAllByText (not getByText): the root-cause skill's label also
      // appears a second time in the "Recommended fix" prose below.
      expect(screen.getAllByText(node.label).length).toBeGreaterThan(0);
    }

    // A struggling skill's whole card is a link to its competency page.
    // Anchored to the start: cost-estimation's own note text now reads
    // "...requires Token counting", so an unanchored match is ambiguous.
    const strugglingLink = screen.getByRole("link", { name: /^Token counting/ });
    expect(strugglingLink).toHaveAttribute("href", "/course/course-1/skills/token-counting");
  });

  it("renders weak edges as dashed paths and met edges as solid", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));
    mockedGetSkillMap.mockResolvedValue(ok(makeSkillMap()));

    const { container } = render(<SkillMapView courseId="course-1" />);
    await screen.findByText("Skill map — Prompt Engineering Basics");

    const paths = container.querySelectorAll("svg path");
    expect(paths.length).toBe(EDGES.length);
    const dashed = container.querySelectorAll("path[stroke-dasharray]");
    expect(dashed.length).toBe(EDGES.filter((e) => e.kind === "weak").length);
  });

  it("shows the legend and the data-driven recommended fix card", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));
    mockedGetSkillMap.mockResolvedValue(ok(makeSkillMap()));

    render(<SkillMapView courseId="course-1" />);
    await screen.findByText("Skill map — Prompt Engineering Basics");

    expect(screen.getByText("prerequisite met")).toBeInTheDocument();
    expect(screen.getByText("weak prerequisite — fix first")).toBeInTheDocument();

    expect(screen.getByText("Recommended fix")).toBeInTheDocument();
    expect(screen.getByText("Cost estimation and Context management")).toBeInTheDocument();
    const startFix = screen.getByRole("link", { name: "Start 4-min fix" });
    // rootCause() resolves to { skill: cost-estimation, prereq: token-counting }
    // for this dataset — the fix points at the weak prereq's own detail page.
    expect(startFix).toHaveAttribute("href", "/course/course-1/skills/token-counting");
  });

  it("disables the By chapter toggle with an explanatory title", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));
    mockedGetSkillMap.mockResolvedValue(ok(makeSkillMap()));

    render(<SkillMapView courseId="course-1" />);
    await screen.findByText("Skill map — Prompt Engineering Basics");

    const byChapter = screen.getByRole("button", { name: "By chapter" });
    expect(byChapter).toBeDisabled();
    expect(byChapter).toHaveAttribute("title", "Coming with the competency backend");
  });

  it("shows an EmptyState with no CTA when the course has no skill graph yet", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));
    mockedGetSkillMap.mockResolvedValue(ok({ nodes: [], edges: [] }));

    render(<SkillMapView courseId="course-1" />);

    expect(await screen.findByText("No skill graph yet")).toBeInTheDocument();
    expect(screen.getByText(/prereq_extraction\.md/)).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows a retryable error banner when the course fails to load", async () => {
    mockedGetCourse.mockResolvedValue(err(500));
    mockedGetSkillMap.mockResolvedValue(ok(makeSkillMap()));

    render(<SkillMapView courseId="course-1" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Loading course failed");
    await waitFor(() => expect(mockedGetCourse).toHaveBeenCalledTimes(1));
  });

  it("shows a retryable error banner when the skill map fails to load", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));
    mockedGetSkillMap.mockResolvedValue(err(500));

    render(<SkillMapView courseId="course-1" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Loading skill map failed");
  });
});
