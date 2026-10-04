import { createClient, type SupabaseClient } from '@supabase/supabase-js'

// Used ONLY for the Google ID-token exchange; our own API issues the real session.
// The Supabase session is never persisted and is signed out locally right after the exchange.
let client: SupabaseClient | undefined

export function getSupabase(): SupabaseClient {
  const url = process.env.EXPO_PUBLIC_SUPABASE_URL
  const publishableKey = process.env.EXPO_PUBLIC_SUPABASE_KEY
  if (!url || !publishableKey) throw new Error('EXPO_PUBLIC_SUPABASE_URL / EXPO_PUBLIC_SUPABASE_KEY are not set')

  client ??= createClient(url, publishableKey, {
    auth: {
      persistSession: false,
      autoRefreshToken: false,
      detectSessionInUrl: false,
    },
  })
  return client
}
