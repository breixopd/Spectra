import { ApiError, type ApiResult } from "@/lib/api";

export function unwrapApiResult<T>(result: ApiResult<T>): T {
  if (result.error) {
    throw result.error;
  }
  if (result.data === null) {
    throw new ApiError(0, null, "Empty response");
  }
  return result.data;
}

export function getApiErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (typeof error.detail === "string") {
      return error.detail;
    }
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Something went wrong";
}
