import { createClient, type User as SupabaseUser, type Session } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL || 'https://your-project.supabase.co'
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY || 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.placeholder-anon-key'

export const supabase = createClient(supabaseUrl, supabaseAnonKey)

export type { SupabaseUser, Session }

let currentAccessToken: string | null = null

supabase.auth.getSession().then(({ data }) => {
  currentAccessToken = data.session?.access_token ?? null
})

supabase.auth.onAuthStateChange((_event, session) => {
  currentAccessToken = session?.access_token ?? null
})

export function getAccessToken(): string | null {
  return currentAccessToken
}

export function setAccessToken(token: string | null) {
  currentAccessToken = token
}
