export class HttpError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details?: unknown,
    /** Extra response headers, e.g. Retry-After on 429. */
    public readonly headers?: Record<string, string>,
  ) {
    super(message);
    this.name = 'HttpError';
  }
}

export const unauthorized = (code = 'UNAUTHORIZED', message = 'Authentication required') =>
  new HttpError(401, code, message);

export const notFound = (message = 'Resource not found') => new HttpError(404, 'NOT_FOUND', message);

export const validationError = (details: unknown) =>
  new HttpError(422, 'VALIDATION_ERROR', 'Request validation failed', details);

export const tooManyAttempts = (retryAfterSeconds: number) =>
  new HttpError(429, 'TOO_MANY_ATTEMPTS', 'Too many attempts, try again later', undefined, {
    'Retry-After': String(Math.max(1, Math.ceil(retryAfterSeconds))),
  });

export const forbidden = (message = 'Not allowed') => new HttpError(403, 'FORBIDDEN', message);
