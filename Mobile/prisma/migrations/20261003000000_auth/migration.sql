-- CreateEnum
CREATE TYPE "interface_language" AS ENUM ('ID', 'EN');

-- CreateEnum
CREATE TYPE "display_mode" AS ENUM ('LIGHT', 'DARK');

-- CreateEnum
CREATE TYPE "auth_provider" AS ENUM ('GOOGLE');

-- CreateEnum
CREATE TYPE "push_platform" AS ENUM ('ANDROID', 'IOS');

-- AlterTable
-- public.users is empty (verified 0 rows). google_linked is removed by spec: it is derived from auth_identities.
-- interface_language/display_mode are converted in place (no DROP) so existing values would be preserved.
ALTER TABLE "users"
ALTER COLUMN "interface_language" DROP DEFAULT,
ALTER COLUMN "display_mode" DROP DEFAULT;

ALTER TABLE "users" DROP COLUMN "google_linked",
ADD COLUMN     "password_hash" VARCHAR,
ALTER COLUMN "id" SET DEFAULT gen_random_uuid(),
ALTER COLUMN "full_name" SET NOT NULL,
ALTER COLUMN "timezone" SET NOT NULL,
ALTER COLUMN "timezone" SET DEFAULT 'Asia/Jakarta',
ALTER COLUMN "interface_language" TYPE "interface_language" USING (upper(coalesce("interface_language", 'id'))::"interface_language"),
ALTER COLUMN "interface_language" SET NOT NULL,
ALTER COLUMN "interface_language" SET DEFAULT 'ID',
ALTER COLUMN "display_mode" TYPE "display_mode" USING (upper(coalesce("display_mode", 'light'))::"display_mode"),
ALTER COLUMN "display_mode" SET NOT NULL,
ALTER COLUMN "display_mode" SET DEFAULT 'LIGHT',
ALTER COLUMN "created_at" SET NOT NULL,
ALTER COLUMN "updated_at" SET NOT NULL;

-- CreateTable
CREATE TABLE "auth_identities" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "user_id" UUID NOT NULL,
    "provider" "auth_provider" NOT NULL,
    "provider_user_id" VARCHAR NOT NULL,
    "supabase_user_id" UUID,
    "email" VARCHAR NOT NULL,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "auth_identities_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "refresh_tokens" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "user_id" UUID NOT NULL,
    "family_id" UUID NOT NULL,
    "token_hash" VARCHAR NOT NULL,
    "expires_at" TIMESTAMPTZ(6) NOT NULL,
    "revoked_at" TIMESTAMPTZ(6),
    "replaced_by_id" UUID,
    "user_agent" VARCHAR,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "refresh_tokens_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "password_reset_otps" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "user_id" UUID NOT NULL,
    "code_hash" VARCHAR NOT NULL,
    "expires_at" TIMESTAMPTZ(6) NOT NULL,
    "attempts" INTEGER NOT NULL DEFAULT 0,
    "consumed_at" TIMESTAMPTZ(6),
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "password_reset_otps_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "push_tokens" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "user_id" UUID NOT NULL,
    "token" VARCHAR NOT NULL,
    "platform" "push_platform" NOT NULL,
    "device_label" VARCHAR,
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "last_seen_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "push_tokens_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "auth_identities_user_id_idx" ON "auth_identities"("user_id");

-- CreateIndex
CREATE UNIQUE INDEX "auth_identities_provider_provider_user_id_key" ON "auth_identities"("provider", "provider_user_id");

-- CreateIndex
CREATE UNIQUE INDEX "refresh_tokens_token_hash_key" ON "refresh_tokens"("token_hash");

-- CreateIndex
CREATE INDEX "refresh_tokens_user_id_idx" ON "refresh_tokens"("user_id");

-- CreateIndex
CREATE INDEX "refresh_tokens_family_id_idx" ON "refresh_tokens"("family_id");

-- CreateIndex
CREATE INDEX "password_reset_otps_user_id_created_at_idx" ON "password_reset_otps"("user_id", "created_at");

-- CreateIndex
CREATE UNIQUE INDEX "push_tokens_token_key" ON "push_tokens"("token");

-- AddForeignKey
ALTER TABLE "auth_identities" ADD CONSTRAINT "auth_identities_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "refresh_tokens" ADD CONSTRAINT "refresh_tokens_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "password_reset_otps" ADD CONSTRAINT "password_reset_otps_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "push_tokens" ADD CONSTRAINT "push_tokens_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;


-- Row Level Security: enabled with NO policies so Supabase anon/authenticated roles cannot read
-- these tables through PostgREST. Prisma connects as "postgres" (rolbypassrls = true, verified).
ALTER TABLE "auth_identities" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "refresh_tokens" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "password_reset_otps" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "push_tokens" ENABLE ROW LEVEL SECURITY;
-- users already has RLS enabled; repeated here so fresh databases match.
ALTER TABLE "users" ENABLE ROW LEVEL SECURITY;
