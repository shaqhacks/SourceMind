import { configure } from "@testing-library/dom";
import "@testing-library/jest-dom/vitest";

// Root cause (found while chasing full-suite-only flakes, never
// reproducible in isolation): @testing-library/dom's own default
// asyncUtilTimeout is 1000ms — every findBy*/waitFor call in this suite
// inherits that ceiling. Under CPU contention (many vitest worker
// threads competing for cores, e.g. a busy CI runner), individual calls
// can legitimately take longer than 1000ms with nothing actually wrong,
// which surfaced as "Unable to find ..." on a different, effectively
// random test each run — reproduced locally by running several full
// suites concurrently to force contention; every failure was this same
// timeout class, never a real assertion mismatch. Raised well above what
// contention needed in that reproduction, comfortably under vitest's own
// (also-raised) 10s testTimeout in vitest.config.ts.
configure({ asyncUtilTimeout: 5000 });

// Node 26's own experimental global `localStorage`/`sessionStorage`
// shadow jsdom's per-window implementation here (window === globalThis
// under vitest's `globals: true`), and are non-functional without a
// `--localstorage-file` flag — every access silently returns undefined.
// The property is configurable, so replace it with a plain in-memory
// Storage implementation for the duration of the test run.
function createMemoryStorage(): Storage {
  const store = new Map<string, string>();
  return {
    get length() {
      return store.size;
    },
    clear: () => store.clear(),
    getItem: (key: string) => (store.has(key) ? store.get(key)! : null),
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    removeItem: (key: string) => {
      store.delete(key);
    },
    setItem: (key: string, value: string) => {
      store.set(key, String(value));
    },
  };
}

for (const key of ["localStorage", "sessionStorage"] as const) {
  Object.defineProperty(globalThis, key, {
    value: createMemoryStorage(),
    configurable: true,
    writable: true,
    enumerable: false,
  });
}

// jsdom doesn't implement matchMedia. useTheme.ts depends on it (to track
// prefers-color-scheme), so any test rendering a component that uses the
// theme system needs this in place before it can render at all.
if (typeof window.matchMedia !== "function") {
  window.matchMedia = (query: string): MediaQueryList => {
    const listeners = new Set<(event: MediaQueryListEvent) => void>();
    const mql = {
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
        listeners.add(listener);
      },
      removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
        listeners.delete(listener);
      },
      dispatchEvent: (event: Event) => {
        listeners.forEach((listener) => listener(event as MediaQueryListEvent));
        return true;
      },
    };
    return mql as MediaQueryList;
  };
}

// jsdom doesn't implement Element.scrollTo at all (throws "not a function").
// The reader's resume-scroll effect calls it with the options-object form;
// this polyfill applies `top` to scrollTop directly and ignores `behavior`
// (jsdom has no layout engine to animate against anyway, and production
// code always wants an instant jump here regardless).
if (typeof Element.prototype.scrollTo !== "function") {
  Element.prototype.scrollTo = function scrollTo(
    this: Element,
    optionsOrX?: ScrollToOptions | number,
    y?: number,
  ): void {
    if (typeof optionsOrX === "object" && optionsOrX !== null) {
      if (typeof optionsOrX.top === "number") this.scrollTop = optionsOrX.top;
      if (typeof optionsOrX.left === "number") this.scrollLeft = optionsOrX.left;
    } else if (typeof optionsOrX === "number") {
      this.scrollLeft = optionsOrX;
      if (typeof y === "number") this.scrollTop = y;
    }
  };
}
