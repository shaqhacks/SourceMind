"use client";

import { useCallback, useEffect, useState } from "react";

import { getCourse } from "@/lib/api/client";
import { describeError, type FetchError } from "@/lib/api/errors";

export interface CourseTitleState {
  title: string | null;
  error: FetchError | null;
  reload: () => void;
}

/**
 * Both skill surfaces only need the real course's title (for the breadcrumb
 * and h1) — the skill data itself is synchronous placeholder data. Shared
 * here so the fetch-on-mount/error/retry boilerplate isn't duplicated
 * between SkillMapView and CompetencyDetailView.
 */
export function useCourseTitle(courseId: string): CourseTitleState {
  const [title, setTitle] = useState<string | null>(null);
  const [error, setError] = useState<FetchError | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let active = true;
    getCourse(courseId).then(({ data, status }) => {
      if (!active) return;
      if (data) {
        setTitle(data.title);
        setError(null);
      } else {
        setError(describeError(status, "Loading course"));
      }
    });
    return () => {
      active = false;
    };
  }, [courseId, reloadToken]);

  const reload = useCallback(() => setReloadToken((n) => n + 1), []);

  return { title, error, reload };
}
