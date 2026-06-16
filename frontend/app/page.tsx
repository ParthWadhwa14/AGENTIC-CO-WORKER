"use client";

import type { Session } from "@supabase/supabase-js";
import { useEffect, useState } from "react";
import { LoginScreen } from "@/components/LoginScreen";
import { WorkspaceApp } from "@/components/WorkspaceApp";
import { isSupabaseConfigured, supabase } from "@/lib/supabase";

export default function Home() {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!isSupabaseConfigured) {
      setLoading(false);
      return;
    }

    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setLoading(false);
    });

    const { data } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
      setLoading(false);
    });

    return () => data.subscription.unsubscribe();
  }, []);

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center p-6">
        <div className="card p-5 text-sm text-[var(--muted)]">
          Loading workspace...
        </div>
      </main>
    );
  }

  if (!session) {
    return <LoginScreen />;
  }

  return <WorkspaceApp session={session} />;
}
