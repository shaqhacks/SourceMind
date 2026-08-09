import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import HtmlPagesView from "@/components/reader/HtmlPagesView";
import { getAssetHtmlManifest, type AssetHtmlManifest } from "@/lib/api/client";

import { err, ok } from "./support/api-result";
import { FakeIntersectionObserver } from "./support/fake-pdfjs";

vi.mock("@/lib/api/client", () => ({
  buildAssetHtmlPageUrl: vi.fn(
    (assetId: string, page: number) => `https://mock/api/assets/${assetId}/html/${page}`,
  ),
  getAssetHtmlManifest: vi.fn(),
}));

const mockedGetAssetHtmlManifest = vi.mocked(getAssetHtmlManifest);

function makeManifest(overrides: Partial<AssetHtmlManifest> = {}): AssetHtmlManifest {
  return { pages: 2, width_px: 800, height_px: 1000, ...overrides };
}

describe("HtmlPagesView", () => {
  let originalIntersectionObserver: typeof IntersectionObserver | undefined;

  beforeEach(() => {
    originalIntersectionObserver = globalThis.IntersectionObserver;
    FakeIntersectionObserver.instances = [];
    globalThis.IntersectionObserver =
      FakeIntersectionObserver as unknown as typeof IntersectionObserver;
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    globalThis.IntersectionObserver = originalIntersectionObserver as typeof IntersectionObserver;
  });

  it("shows a loading state before the manifest resolves", () => {
    mockedGetAssetHtmlManifest.mockReturnValue(new Promise(() => {}));

    render(<HtmlPagesView assetId="asset-loading" pageStart={1} pageEnd={1} />);

    expect(screen.getByRole("status")).toHaveTextContent(/loading enhanced pages/i);
  });

  it("calls getAssetHtmlManifest for the asset", async () => {
    mockedGetAssetHtmlManifest.mockResolvedValue(ok(makeManifest()));

    render(<HtmlPagesView assetId="asset-manifest-call" pageStart={1} pageEnd={1} />);

    await waitFor(() =>
      expect(mockedGetAssetHtmlManifest).toHaveBeenCalledWith("asset-manifest-call"),
    );
  });

  it("renders one sandboxed iframe per page in the range, with the correct src and aspect-ratio sizing", async () => {
    mockedGetAssetHtmlManifest.mockResolvedValue(ok(makeManifest({ width_px: 800, height_px: 1000 })));

    render(<HtmlPagesView assetId="asset-range-rendering" pageStart={1} pageEnd={2} />);

    await waitFor(() => expect(FakeIntersectionObserver.instances).toHaveLength(2));
    // jsdom has no real IntersectionObserver support in this test, but a
    // fake one IS installed above, so pages start hidden behind their
    // placeholder — trigger both to inspect the actual iframes.
    act(() => {
      for (const observer of FakeIntersectionObserver.instances) {
        for (const el of observer.observed) observer.triggerIntersect(el);
      }
    });

    const iframe1 = (await screen.findByTitle("Page 1")) as HTMLIFrameElement;
    const iframe2 = screen.getByTitle("Page 2") as HTMLIFrameElement;

    expect(iframe1).toHaveAttribute(
      "src",
      "https://mock/api/assets/asset-range-rendering/html/1",
    );
    expect(iframe2).toHaveAttribute(
      "src",
      "https://mock/api/assets/asset-range-rendering/html/2",
    );
    // sandbox="" (present, empty) — the most restrictive sandboxing:
    // scripts/forms/top-navigation/etc. all blocked. This is the
    // security-relevant assertion the feature depends on.
    expect(iframe1).toHaveAttribute("sandbox", "");
    expect(iframe2).toHaveAttribute("sandbox", "");

    const container1 = screen.getByTestId("html-page-1");
    expect(container1.style.aspectRatio).toBe("800 / 1000");
  });

  it("lazily mounts only a page that has scrolled near the viewport", async () => {
    mockedGetAssetHtmlManifest.mockResolvedValue(ok(makeManifest()));

    render(<HtmlPagesView assetId="asset-lazy-mount" pageStart={1} pageEnd={2} />);

    await waitFor(() => expect(FakeIntersectionObserver.instances).toHaveLength(2));
    expect(screen.queryByTitle("Page 1")).not.toBeInTheDocument();
    expect(screen.queryByTitle("Page 2")).not.toBeInTheDocument();
    expect(screen.getByTestId("html-page-1")).toHaveTextContent("Page 1");
    expect(screen.getByTestId("html-page-2")).toHaveTextContent("Page 2");

    const page1Container = screen.getByTestId("html-page-1");
    // Awaited: the observer registers in a mount effect (same race class as
    // pdf-note.test.tsx's helper — never grab instances synchronously).
    const observerForPage1 = await waitFor(() => {
      const found = FakeIntersectionObserver.instances.find((observer) =>
        observer.observed.includes(page1Container),
      );
      if (!found) throw new Error("page observer not registered yet");
      return found;
    });
    act(() => {
      observerForPage1.triggerIntersect(page1Container);
    });

    expect(await screen.findByTitle("Page 1")).toBeInTheDocument();
    // Page 2's own observer never fired — still just its placeholder.
    expect(screen.queryByTitle("Page 2")).not.toBeInTheDocument();
  });

  it("shows a retryable error banner when the manifest fails to load", async () => {
    mockedGetAssetHtmlManifest.mockResolvedValueOnce(err(404));

    render(<HtmlPagesView assetId="asset-error" pageStart={1} pageEnd={1} />);

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/could not load the enhanced pages/i);

    mockedGetAssetHtmlManifest.mockResolvedValueOnce(ok(makeManifest()));
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("shows a per-page error when that page's iframe fails to load, without affecting other pages", async () => {
    mockedGetAssetHtmlManifest.mockResolvedValue(ok(makeManifest()));
    const addEventListenerSpy = vi.spyOn(HTMLIFrameElement.prototype, "addEventListener");

    render(<HtmlPagesView assetId="asset-iframe-error" pageStart={1} pageEnd={2} />);
    await waitFor(() => expect(FakeIntersectionObserver.instances).toHaveLength(2));
    act(() => {
      for (const observer of FakeIntersectionObserver.instances) {
        for (const el of observer.observed) observer.triggerIntersect(el);
      }
    });

    const iframe1 = await screen.findByTitle("Page 1");
    try {
      await waitFor(() => {
        const listenerAttached = addEventListenerSpy.mock.calls.some(
          (call, index) =>
            addEventListenerSpy.mock.contexts[index] === iframe1 && call[0] === "error",
        );
        expect(listenerAttached).toBe(true);
      });

      act(() => {
        fireEvent.error(iframe1);
      });
    } finally {
      addEventListenerSpy.mockRestore();
    }

    expect(await screen.findByText(/could not render page 1/i)).toBeInTheDocument();
    expect(screen.getByTitle("Page 2")).toBeInTheDocument();
  });

  // Text selection inside the sandbox="" iframe is intentionally not
  // covered here: jsdom doesn't render real cross-document iframe content
  // or support genuine text selection, so there's nothing meaningful a
  // test could assert. Per the WHATWG HTML sandbox spec, selection isn't
  // gated by any allow-* token (only privileged capabilities like
  // scripts/forms/top-navigation are), so this should work in a real
  // browser — see the final report for this finding rather than a test
  // that can't actually verify it.
});
