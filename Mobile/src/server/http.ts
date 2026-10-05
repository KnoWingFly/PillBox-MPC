import { z } from 'zod';

import { HttpError, validationError } from './errors';

type Handler<P> = (request: Request, params: P) => Promise<Response>;

export function json(body: unknown, status = 200): Response {
  return Response.json(body, { status });
}

export function noContent(): Response {
  return new Response(null, { status: 204 });
}

export function errorResponse(status: number, code: string, message: string, details?: unknown): Response {
  return json({ error: details === undefined ? { code, message } : { code, message, details } }, status);
}

// Wraps a route handler: known errors map to the envelope, everything else becomes
// a 500 without leaking internals (the real error goes to the server log only).
export function route<P = Record<string, string>>(handler: Handler<P>): Handler<P> {
  return async (request, params) => {
    try {
      return await handler(request, params);
    } catch (err) {
      if (err instanceof HttpError) return errorResponse(err.status, err.code, err.message, err.details);
      console.error('[api] unexpected error', request.method, new URL(request.url).pathname, err);
      return errorResponse(500, 'INTERNAL_ERROR', 'Internal server error');
    }
  };
}

export async function parseBody<S extends z.ZodType>(request: Request, schema: S): Promise<z.infer<S>> {
  let raw: unknown;
  try {
    const text = await request.text();
    raw = text ? JSON.parse(text) : {};
  } catch {
    throw validationError([{ path: '', message: 'Body must be valid JSON' }]);
  }
  const result = schema.safeParse(raw);
  if (!result.success) {
    throw validationError(
      result.error.issues.map((issue) => ({ path: issue.path.join('.'), message: issue.message })),
    );
  }
  return result.data;
}

export function userAgent(request: Request): string | null {
  return request.headers.get('user-agent')?.slice(0, 255) ?? null;
}
