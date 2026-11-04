-- CreateTable
-- Rate-limit counters for the auth endpoints (src/server/rate-limit.ts). Additive only.
CREATE TABLE "auth_attempts" (
    "key" VARCHAR(64) NOT NULL,
    "count" INTEGER NOT NULL DEFAULT 0,
    "window_start" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "locked_until" TIMESTAMPTZ(6),

    CONSTRAINT "auth_attempts_pkey" PRIMARY KEY ("key")
);

-- CreateIndex
CREATE INDEX "auth_attempts_window_start_idx" ON "auth_attempts"("window_start");

-- Same rule as the other account tables: only the server's privileged role reads or writes it.
ALTER TABLE "auth_attempts" ENABLE ROW LEVEL SECURITY;
