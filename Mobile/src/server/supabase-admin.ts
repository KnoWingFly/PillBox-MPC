import { createClient, type SupabaseClient } from '@supabase/supabase-js';

import { env } from './env';

let client: SupabaseClient | undefined;

// Admin client authenticated with the secret key (sb_secret_...). Server-only: never import from app code.
export function supabaseAdmin(): SupabaseClient {
  client ??= createClient(env.supabaseUrl, env.supabaseSecretKey, {
    auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
  });
  return client;
}
