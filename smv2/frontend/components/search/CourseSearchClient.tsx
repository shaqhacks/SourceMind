"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import SearchBar from "@/components/search/SearchBar";
import SearchResults from "@/components/search/SearchResults";
import {
  listCourses,
  searchCourse,
  type CourseOut,
  type SearchResultOut,
} from "@/lib/api/client";

const PAGE_SIZE = 10;

interface SubmittedSearch {
  courseId: string;
  query: string;
  documentTypes: string[];
}

function appendUniqueResults(current: SearchResultOut[], incoming: SearchResultOut[]) {
  const seen = new Set(current.map((item) => item.cursor_token));
  const unique = incoming.filter((item) => {
    if (seen.has(item.cursor_token)) return false;
    seen.add(item.cursor_token);
    return true;
  });
  return [...current, ...unique];
}

export default function CourseSearchClient() {
  const [courses, setCourses] = useState<CourseOut[]>([]);
  const [coursesLoading, setCoursesLoading] = useState(true);
  const [coursesError, setCoursesError] = useState<string | null>(null);
  const [selectedCourseId, setSelectedCourseId] = useState("");
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [documentTypes, setDocumentTypes] = useState<string[]>([]);
  const [results, setResults] = useState<SearchResultOut[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [submittedSearch, setSubmittedSearch] = useState<SubmittedSearch | null>(null);
  const latestRequestId = useRef(0);

  useEffect(() => {
    let active = true;
    listCourses().then(({ data, ok }) => {
      if (!active) return;
      if (!ok || !data) {
        setCoursesError("Courses could not be loaded.");
        setCoursesLoading(false);
        return;
      }
      setCourses(data);
      setSelectedCourseId((current) =>
        current && data.some((course) => course.id === current) ? current : data[0]?.id ?? "",
      );
      setCoursesLoading(false);
    });
    return () => {
      active = false;
    };
  }, []);

  const selectedCourse = useMemo(
    () => courses.find((course) => course.id === selectedCourseId) ?? null,
    [courses, selectedCourseId],
  );

  function invalidateSearchWork() {
    latestRequestId.current += 1;
    setSearchLoading(false);
    setSearchError(null);
    setResults([]);
    setNextCursor(null);
    setHasSearched(false);
    setSubmittedQuery("");
    setSubmittedSearch(null);
  }

  async function runSearch(cursor?: string | null) {
    const isNextPage = Boolean(cursor);
    const params = isNextPage
      ? submittedSearch
      : {
          courseId: selectedCourseId,
          query: query.trim(),
          documentTypes: [...documentTypes],
        };
    if (!params || !params.courseId || params.query.length === 0) return;
    const requestId = latestRequestId.current + 1;
    latestRequestId.current = requestId;
    setSearchLoading(true);
    setSearchError(null);
    setHasSearched(true);
    setSubmittedQuery(params.query);
    setSubmittedSearch(params);

    let result;
    try {
      result = await searchCourse(params.courseId, params.query, {
        documentTypes: params.documentTypes,
        cursor: cursor ?? undefined,
        limit: PAGE_SIZE,
      });
    } catch {
      if (latestRequestId.current !== requestId) return;
      setSearchError("Search failed. Try again.");
      setSearchLoading(false);
      return;
    }

    if (latestRequestId.current !== requestId) return;

    const { data, ok } = result;
    if (!ok || !data) {
      setSearchError("Search failed. Try again.");
      setSearchLoading(false);
      return;
    }

    setResults((current) => (isNextPage ? appendUniqueResults(current, data.items) : data.items));
    setNextCursor(data.next_cursor);
    setSearchLoading(false);
  }

  if (coursesLoading) {
    return <p className="p-8 text-sm text-muted-foreground">Loading courses...</p>;
  }

  if (coursesError) {
    return (
      <div className="p-8">
        <div role="alert" className="rounded-md border border-danger/30 bg-danger/10 p-4 text-sm">
          {coursesError}
        </div>
      </div>
    );
  }

  if (courses.length === 0) {
    return (
      <div className="p-8 text-sm text-muted-foreground">
        Add a course before searching your course text.
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-6">
      <div>
        <h1 className="font-heading text-3xl">Search</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Search within the selected course across source text, lessons, notes, and highlights.
        </p>
      </div>
      <SearchBar
        courses={courses}
        selectedCourseId={selectedCourseId}
        query={query}
        documentTypes={documentTypes}
        loading={searchLoading}
        onCourseChange={(courseId) => {
          setSelectedCourseId(courseId);
          invalidateSearchWork();
        }}
        onQueryChange={setQuery}
        onDocumentTypesChange={setDocumentTypes}
        onSubmit={() => void runSearch(null)}
      />
      <SearchResults
        courseTitle={selectedCourse?.title ?? "this course"}
        query={submittedQuery}
        loading={searchLoading}
        error={searchError}
        results={results}
        nextCursor={nextCursor}
        hasSearched={hasSearched}
        onLoadMore={() => void runSearch(nextCursor)}
      />
    </div>
  );
}
