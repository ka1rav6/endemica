import { ApiError, NetworkError } from '@/services/client';

export function describeError(error: unknown, context?: string): string {
  if (error instanceof NetworkError) {
    return `The backend could not be reached. ${error.message} Start it with \`just dev-backend\`, or load the cached snapshot with \`just snapshot-load\`.`;
  }
  if (error instanceof ApiError) {
    if (error.status === 409) {
      return `${error.message} Prepare the datasets with \`just data-fetch && just data-build && just data-load\`.`;
    }
    if (error.status === 502) {
      return `${error.message} Previously cached data is unaffected.`;
    }
    const details = error.details.map((d) => d.message).join('; ');
    return details ? `${error.message} (${details})` : error.message;
  }
  if (error instanceof Error) return error.message;
  return context ? `${context} failed for an unknown reason.` : 'An unknown error occurred.';
}
