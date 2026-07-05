import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

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
    expect(result.current).toEqual({ job: null, error: null, done: false });
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
    expect(result.current).toEqual({ job: null, error: null, done: false });
  });

  it("closes the stream on unmount", () => {
    const { unmount } = renderHook(() => useJobEvents("job-1"));
    const source = FakeEventSource.instances[0];

    unmount();

    expect(source.closed).toBe(true);
  });
});
