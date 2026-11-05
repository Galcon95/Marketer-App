/**
 * Runs before every page request: refreshes the Supabase session cookies and sends visitors who are not signed
 * in to /login (and signed-in users away from it). This only guards the pages; the FastAPI server checks the
 * access token of every API request itself.
 */

import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

/** Pages that are open without signing in: the login page and the link in the confirmation email. */
const PUBLIC_PATHS = ["/login", "/auth/"];

export async function proxy(request: NextRequest) {
  let response = NextResponse.next({ request });
  const supabase = createServerClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      // A refreshed session is written to the request (for this render) and to the response (for the browser).
      setAll: (cookies) => {
        cookies.forEach(({ name, value }) => request.cookies.set(name, value));
        response = NextResponse.next({ request });
        cookies.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
      },
    },
  });

  // getClaims verifies the token's signature (Supabase's public keys), unlike getSession, which trusts the cookie.
  const { data } = await supabase.auth.getClaims();
  const signedIn = Boolean(data?.claims);
  const path = request.nextUrl.pathname;
  const isPublic = PUBLIC_PATHS.some((p) => path.startsWith(p));

  if (!signedIn && !isPublic) return redirect(request, "/login", response);
  if (signedIn && path === "/login") return redirect(request, "/", response);
  return response;
}

/** Redirect to `path`, keeping the session cookies Supabase may just have refreshed in `response`. */
function redirect(request: NextRequest, path: string, response: NextResponse) {
  const to = NextResponse.redirect(new URL(path, request.url));
  response.cookies.getAll().forEach((cookie) => to.cookies.set(cookie));
  return to;
}

export const config = {
  // Every page, not Next.js internals (/_next/…, including the dev server's hot reload, and /__nextjs_…: redirecting
  // those to /login makes the page reload endlessly), static files and images.
  matcher: ["/((?!_next/|__nextjs|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)"],
};
