import { cancelJob, type ApiErrorDetail, type ApiResult, type JobOut } from "@/lib/api/client";
import { apiErrorDetail } from "@/lib/api/errors";

export class CancelJobError extends Error {
  readonly status?: number;
  readonly detail: ApiErrorDetail | null;
  readonly responseError?: unknown;

  constructor(result: ApiResult<JobOut>) {
    super(result.status ? `Cancelling generation failed (HTTP ${result.status}).` : "Cancelling generation failed.");
    this.name = "CancelJobError";
    this.status = result.status;
    this.detail = apiErrorDetail(result.error);
    this.responseError = result.error;
  }
}

export async function cancelGenerationJob(jobId: string): Promise<void> {
  const result = await cancelJob(jobId);
  if (!result.ok) throw new CancelJobError(result);
}
