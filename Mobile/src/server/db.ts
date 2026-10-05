// The ONLY place Prisma Client is created. Swap the driver/adapter here
// (e.g. a Workers-compatible adapter) without touching the rest of the server.
import { PrismaClient } from '@prisma/client';

const globalForPrisma = globalThis as unknown as { __prisma?: PrismaClient };

const isNew = !globalForPrisma.__prisma;
export const db: PrismaClient = globalForPrisma.__prisma ?? new PrismaClient();

// Reuse one client across dev-server reloads instead of opening new pools.
if (process.env.NODE_ENV !== 'production') globalForPrisma.__prisma = db;

// Open the connection as soon as a route loads, so the TLS/pool handshake (seconds on a
// slow link) overlaps with request parsing and bcrypt instead of adding to the first query.
if (isNew) db.$connect().catch((err) => console.error('[db] initial connect failed', err));
