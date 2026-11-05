"use client";

/**
 * Login page ("/login"): sign in with email and password, or create an account (Supabase Auth). A new account
 * must be confirmed with the link in the email Supabase sends (handled by app/auth/confirm/route.ts).
 */

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { BookOpen, LogIn, UserPlus } from "lucide-react";
import { supabase } from "@/lib/supabase";
import { Button, Card, ErrorNote } from "@/components/ui";

/** Shortest password accepted when signing up; Supabase's default minimum is 6. */
const MIN_PASSWORD = 8;

export default function LoginPage() {
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const signup = mode === "signup";
  const router = useRouter();

  /** Sign in (then open the app) or sign up (then ask the user to confirm their email). */
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const email = String(form.get("email")).trim();
    const password = String(form.get("password"));
    setError(null);
    setNotice(null);
    if (signup && password.length < MIN_PASSWORD) {
      setError(`The password needs at least ${MIN_PASSWORD} characters.`);
      return;
    }
    setBusy(true);
    const auth = supabase().auth;
    const { data, error } = signup
      ? await auth.signUp({ email, password, options: { emailRedirectTo: `${location.origin}/auth/confirm` } })
      : await auth.signInWithPassword({ email, password });
    setBusy(false);
    if (error) setError(error.message);
    else if (data.session) {
      router.replace("/");
      router.refresh(); // reload with the new session cookies, so proxy.ts lets the request through
    }
    else setNotice(`Almost done: open the link we sent to ${email} to confirm your account, then sign in.`);
  }

  /** Switch between "Sign in" and "Create account" and clear the messages. */
  function toggleMode() {
    setMode(signup ? "signin" : "signup");
    setError(null);
    setNotice(null);
  }

  return (
    <div className="bc-root login-page">
      <Card title={signup ? "Create your account" : "Sign in to Marketer App"} icon={BookOpen}>
        <form className="login-form" onSubmit={submit}>
          <div className="bc-field">
            <label className="bc-label" htmlFor="login-email">Email</label>
            <input id="login-email" name="email" type="email" autoComplete="email" required className="bc-input" />
          </div>
          <div className="bc-field">
            <label className="bc-label" htmlFor="login-password">Password</label>
            <input id="login-password" name="password" type="password" required className="bc-input"
              autoComplete={signup ? "new-password" : "current-password"} />
            {signup && <span className="bc-hint">At least {MIN_PASSWORD} characters.</span>}
          </div>
          {error && <ErrorNote>{error}</ErrorNote>}
          {notice && <p className="bc-hint" role="status">{notice}</p>}
          <Button type="submit" icon={signup ? UserPlus : LogIn} loading={busy}>
            {signup ? "Create account" : "Sign in"}
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={toggleMode}>
            {signup ? "I already have an account" : "New here? Create an account"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
