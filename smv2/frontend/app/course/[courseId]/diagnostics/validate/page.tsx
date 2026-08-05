import DiagnosticValidation from "@/components/diagnostics/DiagnosticValidation";
import WorkspaceModeGate from "@/components/workspace/WorkspaceModeGate";

export default async function DiagnosticValidationPage({ params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await params;
  return (
    <WorkspaceModeGate courseId={courseId}>
      <DiagnosticValidation courseId={courseId} />
    </WorkspaceModeGate>
  );
}
