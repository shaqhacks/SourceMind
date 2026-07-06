import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import ChapterMasteryBar from "@/components/chapter/ChapterMasteryBar";

describe("ChapterMasteryBar", () => {
  afterEach(() => {
    cleanup();
  });

  it("shows the empty state when there are no attempts yet", () => {
    render(<ChapterMasteryBar stats={null} />);

    expect(screen.getByText(/no attempts yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("also shows the empty state for a zero-attempt stats object (not just null)", () => {
    render(<ChapterMasteryBar stats={{ attempts: 0, best_score: null, latest_score: null }} />);

    expect(screen.getByText(/no attempts yet/i)).toBeInTheDocument();
  });

  it("renders best_score as the headline percentage with correct progressbar aria", () => {
    render(<ChapterMasteryBar stats={{ attempts: 3, best_score: 0.8, latest_score: 0.6 }} />);

    expect(screen.getByText("Chapter mastery: 80%")).toBeInTheDocument();

    const bar = screen.getByRole("progressbar", { name: /chapter mastery/i });
    expect(bar).toHaveAttribute("aria-valuenow", "80");
    expect(bar).toHaveAttribute("aria-valuemin", "0");
    expect(bar).toHaveAttribute("aria-valuemax", "100");
  });

  it("shows latest_score as secondary text alongside the headline", () => {
    render(<ChapterMasteryBar stats={{ attempts: 3, best_score: 0.8, latest_score: 0.6 }} />);

    expect(screen.getByText("Latest: 60%")).toBeInTheDocument();
  });

  it("omits the latest-score text when latest_score is null", () => {
    render(<ChapterMasteryBar stats={{ attempts: 1, best_score: 0.5, latest_score: null }} />);

    expect(screen.queryByText(/latest:/i)).not.toBeInTheDocument();
  });

  it("renders a real width-based fill proportional to best_score, not color alone", () => {
    render(<ChapterMasteryBar stats={{ attempts: 2, best_score: 0.42, latest_score: 0.42 }} />);

    const bar = screen.getByRole("progressbar");
    const fill = bar.firstElementChild as HTMLElement;
    expect(fill.style.width).toBe("42%");
  });
});
