import TestAttemptClient from "@/components/test/TestAttemptClient";

interface TestAttemptPageProps {
  params: Promise<{ courseId: string; attemptId: string }>;
}

export default async function TestAttemptPage({ params }: TestAttemptPageProps) {
  const { courseId, attemptId } = await params;

  return <TestAttemptClient courseId={courseId} attemptId={attemptId} />;
}
