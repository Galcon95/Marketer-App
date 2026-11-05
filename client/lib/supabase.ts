/**
 * Supabase Auth in the browser: the shared client (session kept in cookies, so proxy.ts can read it too) and
 * the access token that lib/api.ts sends to the FastAPI server.
 */

import { createBrowserClient } from "@supabase/ssr";

/** Supabase project URL and publishable key from .env.local (see .env.example); both are public. */
export const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL!;
export const SUPABASE_KEY = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!;

/** The browser's Supabase client (createBrowserClient returns the same instance on every call). */
export function supabase() {
  return createBrowserClient(SUPABASE_URL, SUPABASE_KEY);
}

/**
 * The signed-in user's access token (a JWT) for the Authorization header of API requests; refreshed by
 * Supabase when it is about to expire. Null when nobody is signed in.
 */
export async function accessToken(): Promise<string | null> {
  const { data } = await supabase().auth.getSession();
  return data.session?.access_token ?? null;
}

/** End the session (clears its cookies) and load the login page (a full load: proxy.ts sees no session). */
export async function signOut() {
  await supabase().auth.signOut();
  window.location.replace("/login");
}
