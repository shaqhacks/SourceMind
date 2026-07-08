import ChapterTestClient from "@/components/chapter/ChapterTestClient";

interface ChapterTestPageProps {
  params: Promise<{ courseId: string; chapterLabel: string }>;
}

function decodeRouteSegment(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

export default async function ChapterTestPage({ params }: ChapterTestPageProps) {
  const { courseId, chapterLabel } = await params;

  return <ChapterTestClient courseId={courseId} chapterLabel={decodeRouteSegment(chapterLabel)} />;
}
