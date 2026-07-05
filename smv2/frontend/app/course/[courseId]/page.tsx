import CourseReaderClient from "@/components/reader/CourseReaderClient";

interface CoursePageProps {
  params: Promise<{ courseId: string }>;
}

/**
 * CourseReaderClient is ssr:false (see its own comment) and does all its
 * own data fetching client-side — same pattern as the dashboard — so this
 * page's only job is unwrapping the (Promise-typed, per this Next.js
 * version) route param and handing the plain id down.
 */
export default async function CoursePage({ params }: CoursePageProps) {
  const { courseId } = await params;

  return <CourseReaderClient courseId={courseId} />;
}
