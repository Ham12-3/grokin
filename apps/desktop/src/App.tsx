import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { SignInScreen } from "@/features/auth/SignInScreen";
import { startAuthSync, useAuthStore } from "@/features/auth/auth-store";
import { HomeScreen } from "@/features/home/HomeScreen";

function Screens() {
  const status = useAuthStore((state) => state.status);

  if (status === "loading") {
    return <main className="bg-background h-screen" aria-busy="true" />;
  }
  return status === "signedIn" ? <HomeScreen /> : <SignInScreen />;
}

function App() {
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: 1 } } }),
  );
  const status = useAuthStore((state) => state.status);

  useEffect(() => startAuthSync(), []);

  // Never show one user's cached data to the next.
  useEffect(() => {
    if (status === "signedOut") queryClient.clear();
  }, [status, queryClient]);

  return (
    <QueryClientProvider client={queryClient}>
      <Screens />
    </QueryClientProvider>
  );
}

export default App;
