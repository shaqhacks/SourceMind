import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useJobEvents } from "@/lib/hooks/useJobEvents";

import { FakeEventSource } from "./support/fake-event-source";

describe("useJobEvents", () => {
  let originalEventSource: typeof EventSource;

  beforeEach(() => {
    originalEventSource = globalThis.EventSource;
    FakeEventSource.instances = [];
    globalThis.EventSource = FakeEventSource as unknown as typeof EventSource;
  });

  afterEach(() => {
    globalThis.EventSource = originalEventSource;
  });

  it("does nothing when jobId is null", () => {
    const { result } = renderHook(() => useJobEvents(null));

    expect(FakeEventSource.instances).toHaveLength(0);
    expect(result.current).toEqual({ job: null, error: null, done: false, stalled: false });
  });

  it("opens a stream against the job's events endpoint", () => {
    renderHook(() => useJobEvents("job-1"));

    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].url).toContain("/api/jobs/job-1/events");
  });

  it("applies update events without closing while status is non-terminal", () => {
    const { result } = renderHook(() => useJobEvents("job-1"));
    const source = FakeEventSource.instances[0];

    act(() => {
      source.emit("update", { id: "job-1", status: "running", progress: null });
    });

    expect(result.current.job).toEqual({ id: "job-1", status: "running", progress: null });
    expect(result.current.done).toBe(false);
    expect(result.current.error).toBeNull();
    expect(source.closed).toBe(false);
  });

  it("closes the stream and marks done on a terminal status", () => {
    const { result } = renderHook(() => useJobEvents("job-1"));
    const source = FakeEventSource.instances[0];

    act(() => {
      source.emit("update", { id: "job-1", status: "succeeded", progress: { stage: "done", pct: 100, message: "ok" } });
    });

    expect(result.current.job?.status).toBe("succeeded");
    expect(result.current.job?.progress).toEqual({ stage: "done", pct: 100, message: "ok" });
    expect(result.current.done).toBe(true);
    expect(source.closed).toBe(true);
  });

  it("surfaces a connection error, closes the stream, and never reconnects", () => {
    const { result } = renderHook(() => useJobEvents("job-1"));
    const source = FakeEventSource.instances[0];

    act(() => {
      source.emitError();
    });

    expect(result.current.error).toBeTruthy();
    expect(source.closed).toBe(true);
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("closes the previous stream and resets state when jobId changes", () => {
    const { result, rerender } = renderHook(
      ({ jobId }: { jobId: string | null }) => useJobEvents(jobId),
      { initialProps: { jobId: "job-1" as string | null } },
    );
    const first = FakeEventSource.instances[0];

    act(() => {
      first.emit("update", { id: "job-1", status: "running", progress: null });
    });
    expect(result.current.job?.status).toBe("running");

    rerender({ jobId: "job-2" });

    expect(first.closed).toBe(true);
    expect(FakeEventSource.instances).toHaveLength(2);
    expect(FakeEventSource.instances[1].url).toContain("/api/jobs/job-2/events");
    expect(result.current).toEqual({ job: null, error: null, done: false, stalled: false });
  });

  it("closes the stream on unmount", () => {
    const { unmount } = renderHook(() => useJobEvents("job-1"));
    const source = FakeEventSource.instances[0];

    unmount();

    expect(source.closed).toBe(true);
  });

  describe("stall detection", () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it("marks the job stalled after 120s with no event", () => {
      const { result } = renderHook(() => useJobEvents("job-1"));

      expect(result.current.stalled).toBe(false);

      act(() => {
        vi.advanceTimersByTime(120_000);
      });

      expect(result.current.stalled).toBe(true);
    });

    it("does not stall before 120s", () => {
      const { result } = renderHook(() => useJobEvents("job-1"));

      act(() => {
        vi.advanceTimersByTime(119_999);
      });

      expect(result.current.stalled).toBe(false);
    });

    it("resets the stall clock on every event instead of accumulating from stream open", () => {
      const { result } = renderHook(() => useJobEvents("job-1"));
      const source = FakeEventSource.instances[0];

      act(() => {
        vi.advanceTimersByTime(90_000);
        source.emit("update", { id: "job-1", status: "running", progress: null });
        vi.advanceTimersByTime(90_000); // 180s since open, but only 90s since the event
      });

      expect(result.current.stalled).toBe(false);

      act(() => {
        vi.advanceTimersByTime(30_000); // now 120s since the event
      });

      expect(result.current.stalled).toBe(true);
    });

    it("clears stalled once a fresh event arrives", () => {
      const { result } = renderHook(() => useJobEvents("job-1"));
      const source = FakeEventSource.instances[0];

      act(() => {
        vi.advanceTimersByTime(120_000);
      });
      expect(result.current.stalled).toBe(true);

      act(() => {
        source.emit("update", { id: "job-1", status: "running", progress: null });
      });

      expect(result.current.stalled).toBe(false);
    });

    it("never reports stalled once the job reaches a terminal status", () => {
      const { result } = renderHook(() => useJobEvents("job-1"));
      const source = FakeEventSource.instances[0];

      act(() => {
        source.emit("update", { id: "job-1", status: "succeeded", progress: null });
        vi.advanceTimersByTime(120_000);
      });

      expect(result.current.done).toBe(true);
      expect(result.current.stalled).toBe(false);
    });
  });
});
