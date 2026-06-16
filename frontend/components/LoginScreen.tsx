"use client";

import { LogIn, Mail } from "lucide-react";
import { useState } from "react";
import {
  isSupabaseConfigured,
  supabase,
  supabaseAnonKey
} from "@/lib/supabase";

export function LoginScreen() {
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);

  async function signInWithGoogle() {
    if (!isSupabaseConfigured) return;
    setError("");
    setMessage("");
    setBusy(true);

    const { data, error: signInError } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/auth/callback`,
        skipBrowserRedirect: true
      }
    });

    if (signInError) {
      setError(signInError.message);
      setBusy(false);
      return;
    }

    if (!data.url) {
      setError("Supabase did not return an OAuth URL.");
      setBusy(false);
      return;
    }

    const url = new URL(data.url);
    if (supabaseAnonKey && !url.searchParams.has("apikey")) {
      url.searchParams.set("apikey", supabaseAnonKey);
    }

    try {
      const check = await fetch(url.toString(), {
        method: "GET",
        redirect: "manual"
      });
      const contentType = check.headers.get("content-type") || "";

      if (check.status >= 400 && contentType.includes("application/json")) {
        const payload = await check.json();
        if (payload?.msg?.includes("provider is not enabled")) {
          setError(
            "Google login is not enabled in Supabase yet. Enable Authentication > Providers > Google in your Supabase dashboard, then try again."
          );
          setBusy(false);
          return;
        }
        setError(payload?.msg || "Supabase rejected the Google login request.");
        setBusy(false);
        return;
      }
    } catch {
      // Some browsers do not expose cross-origin OAuth preflight details.
      // Continue with the redirect and let Supabase/Google handle it.
    }

    window.location.assign(url.toString());
  }

  async function signInWithEmail() {
    if (!isSupabaseConfigured || !email.trim()) return;
    setError("");
    setMessage("");
    setBusy(true);

    const { error: otpError } = await supabase.auth.signInWithOtp({
      email: email.trim(),
      options: {
        emailRedirectTo: `${window.location.origin}/auth/callback`
      }
    });

    if (otpError) {
      setError(otpError.message);
    } else {
      setMessage("Check your email for the login link.");
    }
    setBusy(false);
  }

  return (
    <main className="min-h-screen p-6">
      <section className="mx-auto flex min-h-[calc(100vh-48px)] max-w-md flex-col justify-center">
        <div className="card p-6 shadow-sm">
          <div className="mb-6">
            <span className="badge">Workspace Agent</span>
            <h1 className="mt-4 text-3xl font-bold tracking-normal">
              Sign in to your workspace
            </h1>
            <p className="mt-3 text-sm leading-6 text-[var(--muted)]">
              Use Google login through Supabase. After login, connect Drive,
              Docs, Sheets, and Gmail only when you choose.
            </p>
          </div>

          {!isSupabaseConfigured ? (
            <div className="mb-4 rounded-lg border border-[var(--border)] bg-[var(--panel-strong)] p-3 text-sm">
              Add `NEXT_PUBLIC_SUPABASE_URL` and
              `NEXT_PUBLIC_SUPABASE_ANON_KEY` in `frontend/.env.local`.
            </div>
          ) : null}

          {error ? (
            <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {error}
            </div>
          ) : null}

          {message ? (
            <div className="mb-4 rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-700">
              {message}
            </div>
          ) : null}

          <button
            className="btn w-full"
            disabled={!isSupabaseConfigured || busy}
            onClick={signInWithGoogle}
          >
            <LogIn size={18} />
            Continue with Google
          </button>

          <div className="my-4 flex items-center gap-3 text-xs text-[var(--muted)]">
            <span className="h-px flex-1 bg-[var(--border)]" />
            or
            <span className="h-px flex-1 bg-[var(--border)]" />
          </div>

          <div className="flex gap-2">
            <input
              className="input"
              onChange={(event) => setEmail(event.target.value)}
              placeholder="Email magic link"
              type="email"
              value={email}
            />
            <button
              className="btn secondary"
              disabled={!isSupabaseConfigured || busy || !email.trim()}
              onClick={signInWithEmail}
            >
              <Mail size={16} />
            </button>
          </div>

          <p className="mt-4 text-xs leading-5 text-[var(--muted)]">
            No premium Supabase features are required. The app uses Supabase
            Auth, Supabase Postgres/Storage, local FastAPI, Qdrant, and Google
            APIs.
          </p>
        </div>
      </section>
    </main>
  );
}
