import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { apiFetch, type Schemas } from "@/lib/api/client";
import { authLogout, errorMessage } from "@/lib/tauri";

/** Phase 1 placeholder: proves the session works. The real layout arrives in phase 2. */
export function HomeScreen() {
  const [signingOut, setSigningOut] = useState(false);
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => apiFetch<Schemas["MeResponse"]>("/me"),
  });

  async function signOut() {
    setSigningOut(true);
    try {
      await authLogout();
    } finally {
      setSigningOut(false);
    }
  }

  return (
    <main className="bg-background text-foreground flex h-screen items-center justify-center p-6">
      <div className="w-full max-w-sm space-y-6 text-center">
        <h1 className="text-2xl font-semibold tracking-tight">Crew</h1>

        {me.isPending && <p className="text-muted-foreground text-sm">Loading your account...</p>}

        {me.isError && (
          <div className="space-y-3">
            <p role="alert" className="text-destructive text-sm">
              {errorMessage(me.error, "Could not load your account.")}
            </p>
            <Button variant="outline" onClick={() => void me.refetch()}>
              Retry
            </Button>
          </div>
        )}

        {me.isSuccess && (
          <p className="text-sm">
            Signed in as <span className="font-medium">{me.data.name ?? me.data.email}</span>
          </p>
        )}

        <Button variant="outline" disabled={signingOut} onClick={() => void signOut()}>
          {signingOut ? "Signing out..." : "Sign out"}
        </Button>
      </div>
    </main>
  );
}
