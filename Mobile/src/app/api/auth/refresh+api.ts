import { json, parseBody, route, userAgent } from '@/server/http';
import { timed } from '@/server/perf';
import { refreshSchema } from '@/server/schemas';
import { rotateRefreshToken } from '@/server/tokens';

export const POST = route(async (request) => {
  const body = await parseBody(request, refreshSchema);
  // One transaction: find, claim, insert, link (see tokens.ts).
  return json(await timed(request, 'rotate_refresh_token', () => rotateRefreshToken(body.refresh_token, userAgent(request))));
});
