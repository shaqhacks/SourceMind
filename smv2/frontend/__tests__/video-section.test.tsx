import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import VideoSection from "@/components/dashboard/VideoSection";
import { LEARNING_VIDEOS } from "@/lib/dashboard/videos";

describe("VideoSection", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    cleanup();
  });

  it("renders privacy-enhanced lazy iframes for every video", () => {
    render(<VideoSection />);
    // getAllByTitle's MatcherOptions (this @testing-library/dom version) has
    // no `selector` field — the title attribute alone is specific enough
    // here since only the <iframe>s in this component carry one.
    const frames = screen.getAllByTitle(/./);
    expect(frames).toHaveLength(LEARNING_VIDEOS.length);
    for (const frame of frames) {
      expect(frame.tagName).toBe("IFRAME");
      expect(frame.getAttribute("src")).toMatch(/^https:\/\/www\.youtube-nocookie\.com\/embed\//);
      expect(frame).toHaveAttribute("loading", "lazy");
    }
  });

  it("collapses and persists the choice", async () => {
    const user = userEvent.setup();
    render(<VideoSection />);

    await user.click(screen.getByRole("button", { name: /learning science/i }));

    expect(screen.queryByTitle(LEARNING_VIDEOS[0].title)).not.toBeInTheDocument();
    expect(window.localStorage.getItem("smv2.dashboard.videos")).toBe("collapsed");
  });

  it("restores a previously collapsed state on mount", () => {
    window.localStorage.setItem("smv2.dashboard.videos", "collapsed");
    render(<VideoSection />);
    expect(screen.queryByTitle(LEARNING_VIDEOS[0].title)).not.toBeInTheDocument();
  });
});
