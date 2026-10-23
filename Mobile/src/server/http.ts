import { Prisma } from '@prisma/client';
import { z } from 'zod';

import { HttpError, validationError } from './errors';
import { timed } from './perf';

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

// Database overloaded or unreachable: pooler client limit, connection pool timeout (P2024),
// unreachable / dropped server (P1001, P1002, P1008, P1017).
const DB_UNAVAILABLE_CODES = new Set(['P1001', 'P1002', 'P1008', 'P1017', 'P2024']);

function isDbUnavailable(err: unknown): boolean {
  if (err instanceof Prisma.PrismaClientInitializationError) return true;
  if (err instanceof Prisma.PrismaClientKnownRequestError) return DB_UNAVAILABLE_CODES.has(err.code);
  if (err instanceof Prisma.PrismaClientUnknownRequestError) return /max client|too many|timed? ?out/i.test(err.message);
  return false;
}

// Wraps a route handler: known errors map to the envelope, everything else becomes
// a 500 without leaking internals (the real error goes to the server log only).
export function route<P = Record<string, string>>(handler: Handler<P>): Handler<P> {
  return async (request, params) => {
    try {
      return await timed(request, 'api_route_total', () => handler(request, params));
    } catch (err) {
      if (err instanceof HttpError) return errorResponse(err.status, err.code, err.message, err.details);
      if (isDbUnavailable(err)) {
        console.warn('[api] database unavailable', request.method, new URL(request.url).pathname, err);
        const res = errorResponse(503, 'SERVICE_UNAVAILABLE', 'Server sedang sibuk. Coba lagi sebentar lagi.');
        res.headers.set('Retry-After', '5');
        return res;
      }
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
