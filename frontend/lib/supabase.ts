import { createClient } from "@supabase/supabase-js";

const rawSupabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
export const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

function normalizeSupabaseUrl(url: string | undefined) {
  if (!url) return "";

  try {
    return new URL(url).origin;
  } catch {
    return url.replace(/\/rest\/v1\/?$/, "").replace(/\/$/, "");
  }
}

export const supabaseUrl = normalizeSupabaseUrl(rawSupabaseUrl);
export const isSupabaseConfigured = Boolean(supabaseUrl && supabaseAnonKey);

export const supabase = createClient(
  supabaseUrl || "https://example.supabase.co",
  supabaseAnonKey || "missing-anon-key"
);
