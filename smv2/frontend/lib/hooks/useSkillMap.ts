"use client";

import { useCallback, useEffect, useState } from "react";

import { getSkillMap, type SkillMapOut } from "@/lib/api/client";
import { describeError, type FetchError } from "@/lib/api/errors";

export interface SkillMapState {
  /** null until the first fetch resolves (loading); an empty {nodes: []}
   * map is a valid, real "no skill graph yet" result, not a loading state. */
  map: SkillMapOut | null;
  error: FetchError | null;
  reload: () => void;
}

/**
 * Shared fetch-on-mount for GET .../skills — three surfaces read the same
 * course skill map (SkillMapView, SkillSnapshotCard, DiagnosisCard), so the
 * fetch/error/retry boilerplate lives here once, same pattern as
 * components/skills/useCourseTitle.ts.
 */
export function useSkillMap(courseId: string): SkillMapState {
  const [map, setMap] = useState<SkillMapOut | null>(null);
  const [error, setError] = useState<FetchError | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let active = true;
    getSkillMap(courseId).then(({ data, status }) => {
      if (!active) return;
      if (data) {
        setMap(data);
        setError(null);
      } else {
        setError(describeError(status, "Loading skill map"));
      }
    });
    return () => {
      active = false;
    };
  }, [courseId, reloadToken]);

  const reload = useCallback(() => setReloadToken((n) => n + 1), []);

  return { map, error, reload };
}
