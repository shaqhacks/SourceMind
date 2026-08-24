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

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api/client", () => ({
  getCourse: vi.fn(),
  getSkillMap: vi.fn(),
  getSkillStatus: vi.fn(() => Promise.resolve({ data: null, ok: true, status: 200 })),
  startCurriculumExtraction: vi.fn(),
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
    is_sample: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    progress: null,
    ...overrides,
  };
}

// Mirrors a six-node map with transparent learner-model evidence attached.
const NODES: SkillNodeOut[] = [
  { id: "tokenization", slug: "tokenization", label: "Tokenization basics", level: 1, status: "retained", readiness_estimate: 0.86, evidence_state: "retained", distinct_item_count: 8 },
  { id: "token-counting", slug: "token-counting", label: "Token counting", level: 1, status: "building", readiness_estimate: 0.31, evidence_state: "building", distinct_item_count: 5 },
  { id: "prompt-structure", slug: "prompt-structure", label: "Prompt structure", level: 1, status: "building", readiness_estimate: 0.58, evidence_state: "building", distinct_item_count: 4 },
  { id: "cost-estimation", slug: "cost-estimation", label: "Cost estimation", level: 2, status: "likely_struggling", readiness_estimate: 0.24, evidence_state: "likely_struggling", distinct_item_count: 6 },
  { id: "context-management", slug: "context-management", label: "Context management", level: 2, status: "watch", readiness_estimate: 0.52, evidence_state: "watch", distinct_item_count: 5 },
  { id: "caching", slug: "caching", label: "Prompt caching", level: 3, status: "insufficient_evidence", readiness_estimate: null, evidence_state: "insufficient_evidence", distinct_item_count: 0 },
];

const EDGES: SkillEdgeOut[] = [
  { from_id: "tokenization", to_id: "token-counting", kind: "ready" },
  { from_id: "token-counting", to_id: "cost-estimation", kind: "review_suggested" },
  { from_id: "token-counting", to_id: "context-management", kind: "review_suggested" },
  { from_id: "prompt-structure", to_id: "context-management", kind: "review_suggested" },
  { from_id: "cost-estimation", to_id: "caching", kind: "review_suggested" },
  { from_id: "context-management", to_id: "caching", kind: "review_suggested" },
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

    // A concept card links to its evidence detail page (the label also
    // appears once in the top "Skill map preview", so match all and assert
    // they point at the same detail page).
    const strugglingLinks = screen.getAllByRole("link", { name: /^Token counting/ });
    expect(strugglingLinks.length).toBeGreaterThan(0);
    for (const link of strugglingLinks) {
      expect(link).toHaveAttribute("href", "/course/course-1/skills/token-counting");
    }
  });

  it("renders weak edges as dashed paths and met edges as solid", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));
    mockedGetSkillMap.mockResolvedValue(ok(makeSkillMap()));

    const { container } = render(<SkillMapView courseId="course-1" />);
    await screen.findByText("Skill map — Prompt Engineering Basics");

    const paths = container.querySelectorAll("svg path");
    expect(paths.length).toBe(EDGES.length);
    const dashed = container.querySelectorAll("path[stroke-dasharray]");
    expect(dashed.length).toBe(EDGES.filter((e) => e.kind === "review_suggested").length);
  });

  it("shows the legend and the evidence-based recommended review card", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));
    mockedGetSkillMap.mockResolvedValue(ok(makeSkillMap()));

    render(<SkillMapView courseId="course-1" />);
    await screen.findByText("Skill map — Prompt Engineering Basics");

    expect(screen.getByText("prerequisite met")).toBeInTheDocument();
    expect(screen.getByText("prerequisite review suggested")).toBeInTheDocument();

    expect(screen.getByText("Recommended review")).toBeInTheDocument();
    expect(screen.getAllByText("Cost estimation").length).toBeGreaterThan(1);
    expect(screen.getByText(/not a claim about the cause of difficulty/i)).toBeInTheDocument();
    const startReview = screen.getByRole("link", { name: "Practice this concept" });
    expect(startReview).toHaveAttribute("href", "/course/course-1/skills/cost-estimation");
  });

  it("disables the By chapter toggle with an explanatory title", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));
    mockedGetSkillMap.mockResolvedValue(ok(makeSkillMap()));

    render(<SkillMapView courseId="course-1" />);
    await screen.findByText("Skill map — Prompt Engineering Basics");

    const byChapter = screen.getByRole("button", { name: "By chapter" });
    expect(byChapter).toBeDisabled();
    expect(byChapter).toHaveAttribute("title", "By-chapter view isn't built yet");
  });

  it("shows a generate CTA when the course has no skill graph yet", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));
    mockedGetSkillMap.mockResolvedValue(ok({ nodes: [], edges: [] }));

    render(<SkillMapView courseId="course-1" />);

    expect(await screen.findByText("No skill graph yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /generate skill map/i })).toBeInTheDocument();
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
