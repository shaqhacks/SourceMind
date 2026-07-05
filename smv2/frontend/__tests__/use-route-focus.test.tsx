import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let mockPathname = "/";

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
}));

// useRouteFocus tracks "has the app ever mounted" in a module-level
// variable (on purpose — it must persist across a page component's own
// mount/unmount on navigation). That means each test needs a genuinely
// fresh module instance, via resetModules() + a dynamic re-import, or
// they'd observe each other's "already mounted" state.
describe("useRouteFocus", () => {
  beforeEach(() => {
    mockPathname = "/";
    vi.resetModules();
  });

  it("does not focus on the app's initial mount", async () => {
    const { useRouteFocus } = await import("@/lib/hooks/useRouteFocus");
    const element = document.createElement("button");
    document.body.appendChild(element);
    const focusSpy = vi.spyOn(element, "focus");
    const ref = { current: element };

    renderHook(() => useRouteFocus(ref));

    expect(focusSpy).not.toHaveBeenCalled();
  });

  it("focuses the ref's element on a subsequent route change", async () => {
    const { useRouteFocus } = await import("@/lib/hooks/useRouteFocus");
    const element = document.createElement("button");
    document.body.appendChild(element);
    const focusSpy = vi.spyOn(element, "focus");
    const ref = { current: element };

    const { rerender } = renderHook(() => useRouteFocus(ref));
    expect(focusSpy).not.toHaveBeenCalled();

    mockPathname = "/other";
    rerender();

    expect(focusSpy).toHaveBeenCalledTimes(1);
  });

  it("does not refocus repeatedly for the same pathname", async () => {
    const { useRouteFocus } = await import("@/lib/hooks/useRouteFocus");
    const element = document.createElement("button");
    document.body.appendChild(element);
    const focusSpy = vi.spyOn(element, "focus");
    const ref = { current: element };

    mockPathname = "/a";
    const { rerender } = renderHook(() => useRouteFocus(ref));
    mockPathname = "/b";
    rerender();
    expect(focusSpy).toHaveBeenCalledTimes(1);

    rerender();
    expect(focusSpy).toHaveBeenCalledTimes(1);
  });

  it("waits for ready=true before focusing, even after the pathname already changed", async () => {
    const { useRouteFocus } = await import("@/lib/hooks/useRouteFocus");
    const element = document.createElement("button");
    document.body.appendChild(element);
    const focusSpy = vi.spyOn(element, "focus");
    const ref = { current: element };

    const { rerender } = renderHook(({ ready }: { ready: boolean }) => useRouteFocus(ref, ready), {
      initialProps: { ready: true },
    });

    mockPathname = "/b";
    rerender({ ready: false });
    expect(focusSpy).not.toHaveBeenCalled();

    rerender({ ready: true });
    expect(focusSpy).toHaveBeenCalledTimes(1);
  });
});
