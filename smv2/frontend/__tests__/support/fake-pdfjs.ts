import { vi } from "vitest";

/**
 * Minimal pdf.js test doubles shared by PdfPagesView's own tests and any
 * reader-integration test that needs to exercise "pages" mode without
 * pulling in the real pdfjs-dist (jsdom has neither DOMMatrix nor Worker,
 * which the real module needs at import time — see PdfPagesView.tsx's own
 * comment on this). Assign via `vi.mock("pdfjs-dist", () => ({...}))`.
 */

export interface FakePdfPage {
  getViewport: ReturnType<typeof vi.fn>;
  render: ReturnType<typeof vi.fn>;
}

export interface FakePdfDocument {
  numPages: number;
  getPage: ReturnType<typeof vi.fn>;
}

/** A page that renders successfully by default; pass `renderError` to
 * exercise the per-page error path instead. The rejection is built lazily
 * inside `render()`'s own vi.fn() — not eagerly at makeFakePage() call
 * time — so it's only ever constructed at the moment something is about
 * to attach a handler to it (the component's render effect does so
 * synchronously); building it eagerly left a window where nothing had
 * subscribed yet, which Node/Vitest flags as an unhandled rejection even
 * though a real handler attaches moments later. */
export function makeFakePage(overrides: { renderError?: unknown } = {}): FakePdfPage {
  return {
    getViewport: vi.fn(({ scale = 1 }: { scale?: number } = {}) => ({
      width: 600 * scale,
      height: 800 * scale,
    })),
    render: vi.fn(() => ({
      promise:
        overrides.renderError !== undefined
          ? Promise.reject(overrides.renderError)
          : Promise.resolve(),
      cancel: vi.fn(),
    })),
  };
}

export function makeFakeDocument(pages: Record<number, FakePdfPage>): FakePdfDocument {
  return {
    numPages: Object.keys(pages).length,
    getPage: vi.fn((pageNumber: number) => {
      const page = pages[pageNumber];
      return page ? Promise.resolve(page) : Promise.reject(new Error(`no page ${pageNumber}`));
    }),
  };
}

/**
 * Minimal IntersectionObserver double — jsdom doesn't implement it at
 * all. Tracks every constructed instance (same `.instances` idiom as
 * FakeEventSource) and every observed element, so a test can call
 * `triggerIntersect(el)` to simulate that element scrolling into view.
 */
export class FakeIntersectionObserver implements IntersectionObserver {
  static instances: FakeIntersectionObserver[] = [];

  readonly root: Element | Document | null = null;
  readonly rootMargin: string = "";
  readonly thresholds: ReadonlyArray<number> = [];
  observed: Element[] = [];
  disconnected = false;
  private callback: IntersectionObserverCallback;

  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback;
    FakeIntersectionObserver.instances.push(this);
  }

  observe(target: Element) {
    this.observed.push(target);
  }

  unobserve(target: Element) {
    this.observed = this.observed.filter((el) => el !== target);
  }

  disconnect() {
    this.disconnected = true;
  }

  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }

  /** Simulates `target` scrolling into view. */
  triggerIntersect(target: Element) {
    this.callback(
      [{ isIntersecting: true, target } as IntersectionObserverEntry],
      this,
    );
  }
}
