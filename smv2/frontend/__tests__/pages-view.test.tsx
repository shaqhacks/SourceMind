import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { getDocument } from "pdfjs-dist";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PagesView from "@/components/reader/PagesView";
import { getAssetHtmlManifest, listAssets, type AssetOut } from "@/lib/api/client";

import { ok } from "./support/api-result";
import { makeFakeDocument, makeFakePage } from "./support/fake-pdfjs";

vi.mock("@/lib/api/client", () => ({
  listAssets: vi.fn(),
  buildAssetFileUrl: vi.fn((assetId: string) => `https://mock/api/assets/${assetId}/file`),
  buildAssetHtmlPageUrl: vi.fn(
    (assetId: string, page: number) => `https://mock/api/assets/${assetId}/html/${page}`,
  ),
  getAssetHtmlManifest: vi.fn(),
}));

// PdfPagesView (the fallback renderer) imports pdfjs-dist at module scope
// — jsdom has neither DOMMatrix nor Worker (see PdfPagesView.tsx's own
// comment), so the real module throws the moment it's evaluated.
vi.mock("pdfjs-dist", () => ({
  GlobalWorkerOptions: { workerPort: null },
  getDocument: vi.fn(),
  TextLayer: class {
    render = vi.fn(() => Promise.resolve());
    cancel = vi.fn();
  },
}));

const mockedListAssets = vi.mocked(listAssets);
const mockedGetAssetHtmlManifest = vi.mocked(getAssetHtmlManifest);
const mockedGetDocument = vi.mocked(getDocument);

function makeAsset(overrides: Partial<AssetOut> & { html_status?: string } = {}): AssetOut {
  return {
    id: "asset-1",
    course_id: "course-x",
    filename: "book.pdf",
    content_type: "application/pdf",
    size_bytes: 1000,
    sha256: "hash",
    page_count: 10,
    status: "stored",
    error: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as AssetOut;
}

describe("PagesView", () => {
  beforeEach(() => {
    mockedGetDocument.mockReturnValue({
      promise: Promise.resolve(makeFakeDocument({ 1: makeFakePage() })),
    } as unknown as ReturnType<typeof getDocument>);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  // Each test uses its own courseId: getAssetHtmlStatus caches the
  // listAssets() result per course at module scope (see
  // lib/reader/htmlPagesStatus.ts) for the lifetime of the test run, not
  // just this file's own mocks — reusing a courseId across tests would
  // silently serve an earlier test's cached (and by-then-wrong) status.

  it("renders HtmlPagesView when the asset's html_status is ready", async () => {
    mockedListAssets.mockResolvedValue(
      ok([makeAsset({ course_id: "course-ready", html_status: "ready" })]),
    );
    mockedGetAssetHtmlManifest.mockResolvedValue(
      ok({ pages: 1, width_px: 800, height_px: 1000 }),
    );

    render(<PagesView courseId="course-ready" assetId="asset-1" pageStart={1} pageEnd={1} />);

    await waitFor(() => expect(mockedGetAssetHtmlManifest).toHaveBeenCalledWith("asset-1"));
    expect(screen.queryByTestId("pdf-page-1")).not.toBeInTheDocument();
    expect(
      screen.queryByText(/enhanced view is being prepared/i),
    ).not.toBeInTheDocument();
  });

  it("renders PdfPagesView plus a non-blocking note when the asset's html_status is converting", async () => {
    mockedListAssets.mockResolvedValue(
      ok([makeAsset({ course_id: "course-converting", html_status: "converting" })]),
    );

    render(
      <PagesView courseId="course-converting" assetId="asset-1" pageStart={1} pageEnd={1} />,
    );

    expect(await screen.findByText(/enhanced view is being prepared/i)).toBeInTheDocument();
    expect(await screen.findByTestId("pdf-page-1")).toBeInTheDocument();
    expect(mockedGetAssetHtmlManifest).not.toHaveBeenCalled();
  });

  it("renders plain PdfPagesView with no note when the asset's html_status is failed", async () => {
    mockedListAssets.mockResolvedValue(
      ok([makeAsset({ course_id: "course-failed", html_status: "failed" })]),
    );

    render(<PagesView courseId="course-failed" assetId="asset-1" pageStart={1} pageEnd={1} />);

    expect(await screen.findByTestId("pdf-page-1")).toBeInTheDocument();
    expect(screen.queryByText(/enhanced view is being prepared/i)).not.toBeInTheDocument();
  });

  it("renders plain PdfPagesView with no note when the asset has no html_status at all (field not yet landed)", async () => {
    // no html_status key at all
    mockedListAssets.mockResolvedValue(ok([makeAsset({ course_id: "course-none" })]));

    render(<PagesView courseId="course-none" assetId="asset-1" pageStart={1} pageEnd={1} />);

    expect(await screen.findByTestId("pdf-page-1")).toBeInTheDocument();
    expect(screen.queryByText(/enhanced view is being prepared/i)).not.toBeInTheDocument();
  });
});
