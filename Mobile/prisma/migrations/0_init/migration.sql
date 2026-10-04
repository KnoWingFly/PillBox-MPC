-- CreateSchema
CREATE SCHEMA IF NOT EXISTS "public";

-- CreateTable
CREATE TABLE "users" (
    "id" UUID NOT NULL,
    "full_name" VARCHAR,
    "email" VARCHAR NOT NULL,
    "phone_number" VARCHAR,
    "timezone" VARCHAR,
    "google_linked" BOOLEAN DEFAULT false,
    "interface_language" VARCHAR DEFAULT 'id',
    "display_mode" VARCHAR DEFAULT 'light',
    "created_at" TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "users_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "users_email_key" ON "users"("email");


-- Existing table already had RLS enabled in Supabase.
ALTER TABLE "users" ENABLE ROW LEVEL SECURITY;
