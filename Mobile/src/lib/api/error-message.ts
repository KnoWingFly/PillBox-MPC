import { Strings } from '@/constants/strings';

import { ApiError } from './client';

// Maps an error to a user-facing Indonesian message (server messages are English, for devs).
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return Strings.apiErrors[err.code] ?? Strings.common.unexpectedError;
  return Strings.common.unexpectedError;
}
