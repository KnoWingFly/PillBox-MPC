import { json, parseBody, route, userAgent } from '@/server/http';
import { refreshSchema } from '@/server/schemas';
import { rotateRefreshToken } from '@/server/tokens';

export const POST = route(async (request) => {
  const body = await parseBody(request, refreshSchema);
  return json(await rotateRefreshToken(body.refresh_token, userAgent(request)));
});
