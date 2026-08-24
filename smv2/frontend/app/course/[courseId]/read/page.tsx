import CourseReaderClient from "@/components/reader/CourseReaderClient";

interface ReadPageProps {
  params: Promise<{ courseId: string }>;
}

/**
 * CourseReaderClient is ssr:false (see its own comment) and does all its
 * own data fetching client-side — this page's only job is unwrapping the
 * (Promise-typed) route param and handing the plain id down.
 */
export default async function ReadPage({ params }: ReadPageProps) {
  const { courseId } = await params;

  return <CourseReaderClient courseId={courseId} />;
}
