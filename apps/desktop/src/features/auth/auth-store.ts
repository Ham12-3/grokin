import { create } from "zustand";
import { authGetTokens, onAuthChanged } from "@/lib/tauri";

export type AuthStatus = "loading" | "signedOut" | "signedIn";

interface AuthStore {
  status: AuthStatus;
  setSignedIn: (signedIn: boolean) => void;
}

export const useAuthStore = create<AuthStore>((set) => ({
  status: "loading",
  setSignedIn: (signedIn) => set({ status: signedIn ? "signedIn" : "signedOut" }),
}));

/**
 * Reads the session from the keychain and follows `auth:changed` from the Rust core.
 * Returns a cleanup function.
 */
export function startAuthSync(): () => void {
  const { setSignedIn } = useAuthStore.getState();
  let stopped = false;
  let unlisten: (() => void) | undefined;

  void onAuthChanged(setSignedIn).then((stop) => {
    if (stopped) stop();
    else unlisten = stop;
  });
  authGetTokens()
    .then((session) => {
      if (!stopped) setSignedIn(session.has_session);
    })
    .catch(() => {
      if (!stopped) setSignedIn(false);
    });

  return () => {
    stopped = true;
    unlisten?.();
  };
}
