import { Strings } from '@/constants/strings';

/** Errors from either server carry a machine `code` (ApiError here, BackendError in lib/api.ts). */
type CodedError = Error & { code: string; userMessage?: string };

function isCoded(err: unknown): err is CodedError {
  return err instanceof Error && typeof (err as { code?: unknown }).code === 'string';
}

/**
 * Maps an error to a user-facing Indonesian message. Server messages are English and for
 * developers (they can name URLs or internals), so they are never shown. `overrides` lets a screen
 * word a code for its own context; `userMessage` is copy already written for the user (e.g. the
 * pillbox's own reason for rejecting a command).
 */
export function errorMessage(err: unknown, overrides: Record<string, string> = {}): string {
  if (!isCoded(err)) return Strings.common.unexpectedError;
  return overrides[err.code] ?? err.userMessage ?? Strings.apiErrors[err.code] ?? Strings.common.unexpectedError;
}

/** "Gagal X: <reason>" for action toasts; just the prefix when the reason is unknown. */
export function failMessage(prefix: string, err: unknown): string {
  const reason = errorMessage(err);
  return reason === Strings.common.unexpectedError ? prefix : Strings.common.failWithReason(prefix, reason);
}
