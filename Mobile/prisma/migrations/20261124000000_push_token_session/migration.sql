-- Push tokens remember the session (refresh-token family) they were registered under, so a phone
-- whose session ended without a logout stops receiving alerts (Mobile/BACKEND_HANDOFF.md item 9).
-- Additive: existing rows get NULL and are left alone by the cleanup.
-- AlterTable
ALTER TABLE "push_tokens" ADD COLUMN "refresh_family_id" UUID;

-- CreateIndex
CREATE INDEX "push_tokens_refresh_family_id_idx" ON "push_tokens"("refresh_family_id");
