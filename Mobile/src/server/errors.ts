export class HttpError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details?: unknown,
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
