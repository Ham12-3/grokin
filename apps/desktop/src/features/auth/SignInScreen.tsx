import { useEffect, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { authStartLogin, errorMessage, onAuthError } from "@/lib/tauri";

type Step = { name: "form" } | { name: "sent"; email: string } | { name: "google" };

export function SignInScreen() {
  const [step, setStep] = useState<Step>({ name: "form" });
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Errors from the deep link (expired or reused code) arrive as an event.
  useEffect(() => {
    let stopped = false;
    let unlisten: (() => void) | undefined;
    void onAuthError((authError) => {
      setError(authError.message);
      setStep({ name: "form" });
    }).then((stop) => {
      if (stopped) stop();
      else unlisten = stop;
    });
    return () => {
      stopped = true;
      unlisten?.();
    };
  }, []);

  async function start(action: () => Promise<void>, next: Step) {
    setBusy(true);
    setError(null);
    try {
      await action();
      setStep(next);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  function submitEmail(event: FormEvent) {
    event.preventDefault();
    const address = email.trim();
    if (!address) return;
    void start(() => authStartLogin("email", address), { name: "sent", email: address });
  }

  return (
    <main className="bg-background text-foreground flex h-screen items-center justify-center p-6">
      <div className="w-full max-w-sm space-y-6">
        <div className="space-y-1 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">Crew</h1>
          <p className="text-muted-foreground text-sm">Sign in to meet your teammates.</p>
        </div>

        {step.name === "sent" && (
          <section className="space-y-4 text-center" aria-live="polite">
            <h2 className="text-lg font-medium">Check your email</h2>
            <p className="text-muted-foreground text-sm">
              We sent a sign-in link to <span className="text-foreground">{step.email}</span>. Open
              it on this computer and Crew will sign you in.
            </p>
            <Button variant="outline" onClick={() => setStep({ name: "form" })}>
              Use a different email
            </Button>
          </section>
        )}

        {step.name === "google" && (
          <section className="space-y-4 text-center" aria-live="polite">
            <h2 className="text-lg font-medium">Finish in your browser</h2>
            <p className="text-muted-foreground text-sm">
              Sign in with Google in the browser window that just opened, then come back here.
            </p>
            <Button variant="outline" onClick={() => setStep({ name: "form" })}>
              Back
            </Button>
          </section>
        )}

        {step.name === "form" && (
          <section className="space-y-4">
            <form className="space-y-3" onSubmit={submitEmail}>
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="email"
                  placeholder="you@example.com"
                  required
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  disabled={busy}
                />
              </div>
              <Button type="submit" className="w-full" disabled={busy || !email.trim()}>
                {busy ? "Sending..." : "Continue with email"}
              </Button>
            </form>
            <div className="text-muted-foreground flex items-center gap-3 text-xs">
              <span className="bg-border h-px flex-1" />
              or
              <span className="bg-border h-px flex-1" />
            </div>
            <Button
              variant="outline"
              className="w-full"
              disabled={busy}
              onClick={() => void start(() => authStartLogin("google"), { name: "google" })}
            >
              Continue with Google
            </Button>
          </section>
        )}

        {error && (
          <p role="alert" className="text-destructive text-center text-sm">
            {error}
          </p>
        )}
      </div>
    </main>
  );
}
