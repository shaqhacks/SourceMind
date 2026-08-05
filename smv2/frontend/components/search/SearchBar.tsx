"use client";

const FILTERS = [
  { value: "section", label: "Sections" },
  { value: "lesson", label: "Lessons" },
  { value: "note", label: "Notes" },
  { value: "highlight", label: "Highlights" },
];

export interface SearchBarProps {
  courses: { id: string; title: string }[];
  selectedCourseId: string;
  query: string;
  documentTypes: string[];
  loading: boolean;
  onCourseChange: (courseId: string) => void;
  onQueryChange: (query: string) => void;
  onDocumentTypesChange: (documentTypes: string[]) => void;
  onSubmit: () => void;
}

export default function SearchBar({
  courses,
  selectedCourseId,
  query,
  documentTypes,
  loading,
  onCourseChange,
  onQueryChange,
  onDocumentTypesChange,
  onSubmit,
}: SearchBarProps) {
  function toggleFilter(value: string) {
    onDocumentTypesChange(
      documentTypes.includes(value)
        ? documentTypes.filter((item) => item !== value)
        : [...documentTypes, value],
    );
  }

  return (
    <form
      role="search"
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <div className="grid gap-3 md:grid-cols-[minmax(180px,260px)_minmax(0,1fr)_auto]">
        <label className="flex flex-col gap-1 text-sm font-medium">
          Course
          <select
            value={selectedCourseId}
            onChange={(event) => onCourseChange(event.target.value)}
            className="h-10 rounded-md border border-divider bg-background px-3 text-sm"
          >
            {courses.map((course) => (
              <option key={course.id} value={course.id}>
                {course.title}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium">
          Search course text
          <input
            type="search"
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            className="h-10 rounded-md border border-divider bg-background px-3 text-sm"
            placeholder="Find a phrase, concept, note, or highlight"
          />
        </label>
        <button
          type="submit"
          disabled={loading || !selectedCourseId || query.trim().length === 0}
          className="h-10 self-end rounded-md bg-accent-700 px-4 text-sm font-semibold text-background hover:bg-accent-800 disabled:opacity-60"
        >
          Search
        </button>
      </div>
      <fieldset className="flex flex-wrap gap-3">
        <legend className="sr-only">Document types</legend>
        {FILTERS.map((filter) => (
          <label key={filter.value} className="flex items-center gap-2 text-sm text-muted-foreground">
            <input
              type="checkbox"
              checked={documentTypes.includes(filter.value)}
              onChange={() => toggleFilter(filter.value)}
            />
            {filter.label}
          </label>
        ))}
      </fieldset>
    </form>
  );
}
