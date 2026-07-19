import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { getDocument } from "pdfjs-dist";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PdfPagesView from "@/components/reader/PdfPagesView";

import { FakeIntersectionObserver, makeFakeDocument, makeFakePage } from "./support/fake-pdfjs";

vi.mock("@/lib/api/client", () => ({
  buildAssetFileUrl: vi.fn((assetId: string) => `https://mock/api/assets/${assetId}/file`),
}));

// jsdom has neither DOMMatrix nor Worker — see PdfPagesView.tsx's own
// comment on why the real module can't be imported here.
vi.mock("pdfjs-dist", () => ({
  GlobalWorkerOptions: { workerPort: null },
  getDocument: vi.fn(),
  TextLayer: class {
    render = vi.fn(() => Promise.resolve());
    cancel = vi.fn();
  },
}));

const mockedGetDocument = vi.mocked(getDocument);

function resolvedTask(doc: ReturnType<typeof makeFakeDocument>) {
  return { promise: Promise.resolve(doc) } as unknown as ReturnType<typeof getDocument>;
}

describe("PdfPagesView", () => {
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

  it("shows a loading state before the document resolves", () => {
    mockedGetDocument.mockReturnValue({
      promise: new Promise(() => {}),
    } as unknown as ReturnType<typeof getDocument>);

    render(<PdfPagesView assetId="asset-loading" pageStart={1} pageEnd={1} />);

    expect(screen.getByRole("status")).toHaveTextContent(/loading original pages/i);
  });

  it("calls getDocument with the asset's file URL", async () => {
    mockedGetDocument.mockReturnValue(resolvedTask(makeFakeDocument({ 1: makeFakePage() })));

    render(<PdfPagesView assetId="asset-url" pageStart={1} pageEnd={1} />);

    await waitFor(() =>
      expect(mockedGetDocument).toHaveBeenCalledWith({
        url: "https://mock/api/assets/asset-url/file",
      }),
    );
  });

  it("renders one page container for every page in the range", async () => {
    mockedGetDocument.mockReturnValue(
      resolvedTask(makeFakeDocument({ 1: makeFakePage(), 2: makeFakePage(), 3: makeFakePage() })),
    );

    render(<PdfPagesView assetId="asset-range" pageStart={1} pageEnd={3} />);

    await waitFor(() => {
      expect(screen.getByTestId("pdf-page-1")).toBeInTheDocument();
      expect(screen.getByTestId("pdf-page-2")).toBeInTheDocument();
      expect(screen.getByTestId("pdf-page-3")).toBeInTheDocument();
    });
  });

  it("lazily renders only a page that has scrolled near the viewport — a 40-page section must not render all its canvases up front", async () => {
    const page1 = makeFakePage();
    const page2 = makeFakePage();
    const doc = makeFakeDocument({ 1: page1, 2: page2 });
    mockedGetDocument.mockReturnValue(resolvedTask(doc));

    render(<PdfPagesView assetId="asset-lazy" pageStart={1} pageEnd={2} />);

    await waitFor(() => expect(FakeIntersectionObserver.instances).toHaveLength(2));
    // Neither page has "intersected" yet — both show their placeholder,
    // and pdf.js is never asked to actually load either page's content.
    expect(screen.getByTestId("pdf-page-1")).toHaveTextContent("Page 1");
    expect(screen.getByTestId("pdf-page-2")).toHaveTextContent("Page 2");
    expect(doc.getPage).not.toHaveBeenCalled();

    const page1Container = screen.getByTestId("pdf-page-1");
    const observerForPage1 = FakeIntersectionObserver.instances.find((observer) =>
      observer.observed.includes(page1Container),
    );
    observerForPage1!.triggerIntersect(page1Container);

    await waitFor(() => expect(doc.getPage).toHaveBeenCalledWith(1));
    expect(doc.getPage).not.toHaveBeenCalledWith(2);
    await waitFor(() => expect(screen.getByLabelText("Page 1")).toBeInTheDocument());
    // Page 2 is still just its placeholder — its own observer never fired.
    expect(screen.getByTestId("pdf-page-2")).toHaveTextContent("Page 2");
  });

  it("shows a retryable error banner when the document fails to load", async () => {
    mockedGetDocument.mockReturnValueOnce({
      promise: Promise.reject(new Error("network fail")),
    } as unknown as ReturnType<typeof getDocument>);

    render(<PdfPagesView assetId="asset-error" pageStart={1} pageEnd={1} />);

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/could not load the original pdf pages/i);

    mockedGetDocument.mockReturnValueOnce(resolvedTask(makeFakeDocument({ 1: makeFakePage() })));
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(screen.getByTestId("pdf-page-1")).toBeInTheDocument();
  });

  it("caches the parsed document per assetId — a remount with the same id doesn't re-fetch", async () => {
    mockedGetDocument.mockReturnValue(resolvedTask(makeFakeDocument({ 1: makeFakePage() })));

    const { unmount } = render(<PdfPagesView assetId="asset-cache" pageStart={1} pageEnd={1} />);
    await waitFor(() => expect(mockedGetDocument).toHaveBeenCalledTimes(1));
    unmount();

    render(<PdfPagesView assetId="asset-cache" pageStart={1} pageEnd={1} />);

    await waitFor(() => expect(screen.getByTestId("pdf-page-1")).toBeInTheDocument());
    expect(mockedGetDocument).toHaveBeenCalledTimes(1);
  });

  it("shows a per-page error when that page's own render fails, without affecting other pages", async () => {
    const failingPage = makeFakePage({ renderError: { name: "RenderError" } });
    const okPage = makeFakePage();
    mockedGetDocument.mockReturnValue(resolvedTask(makeFakeDocument({ 1: failingPage, 2: okPage })));

    render(<PdfPagesView assetId="asset-page-error" pageStart={1} pageEnd={2} />);
    await waitFor(() => expect(FakeIntersectionObserver.instances).toHaveLength(2));

    for (const observer of FakeIntersectionObserver.instances) {
      for (const el of observer.observed) observer.triggerIntersect(el);
    }

    expect(await screen.findByText(/could not render page 1/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Page 2")).toBeInTheDocument();
  });
});
