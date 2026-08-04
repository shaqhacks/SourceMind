import DiagnosticValidation from "@/components/diagnostics/DiagnosticValidation";

export default async function DiagnosticValidationPage({ params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await params;
  return <DiagnosticValidation courseId={courseId} />;
}
