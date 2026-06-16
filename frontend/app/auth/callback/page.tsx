"use client";

import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";

export default function AuthCallbackPage() {
  const [message, setMessage] = useState("Completing sign in...");

  useEffect(() => {
    async function completeSignIn() {
      const params = new URLSearchParams(window.location.search);
      const code = params.get("code");
      const error = params.get("error_description") || params.get("error");

      if (error) {
        setMessage(`Sign in failed: ${error}`);
        window.setTimeout(() => window.location.replace("/"), 1800);
        return;
      }

      if (!code) {
        setMessage("No sign-in code was returned.");
        window.setTimeout(() => window.location.replace("/"), 1800);
        return;
      }

      const { error: exchangeError } = await supabase.auth.exchangeCodeForSession(
        code
      );
      if (exchangeError) {
        setMessage(`Sign in failed: ${exchangeError.message}`);
        window.setTimeout(() => window.location.replace("/"), 2200);
        return;
      }

      window.location.replace("/");
    }

    completeSignIn();
  }, []);

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="card flex items-center gap-3 p-5 text-sm">
        <Loader2 className="animate-spin text-[var(--accent)]" size={18} />
        {message}
      </div>
    </main>
  );
}
