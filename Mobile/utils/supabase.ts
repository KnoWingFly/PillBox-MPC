import { createClient, type SupabaseClient } from '@supabase/supabase-js'
import { Platform } from 'react-native'

// Used only to verify Google sign-in; the app's own auth API issues the lasting session.
let client: SupabaseClient | undefined

export function getSupabase(): SupabaseClient {
  const url = process.env.EXPO_PUBLIC_SUPABASE_URL
  const publishableKey = process.env.EXPO_PUBLIC_SUPABASE_KEY
  if (!url || !publishableKey) throw new Error('EXPO_PUBLIC_SUPABASE_URL / EXPO_PUBLIC_SUPABASE_KEY are not set')

  client ??= createClient(url, publishableKey, {
    auth: {
      persistSession: Platform.OS === 'web',
      autoRefreshToken: false,
      detectSessionInUrl: false,
      flowType: 'pkce',
      ...(Platform.OS === 'web' && typeof window !== 'undefined' ? { storage: window.sessionStorage } : {}),
    },
  })
  return client
}
