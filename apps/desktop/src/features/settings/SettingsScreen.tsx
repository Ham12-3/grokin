import { ConnectorsSection } from "./ConnectorsSection";
import { UpdatesSection } from "./UpdatesSection";
import { VaultSection } from "./VaultSection";

/** App-wide settings: connected apps, the Vault and updates. */
export function SettingsScreen() {
  return (
    <section aria-label="Settings" className="min-w-0 flex-1 overflow-y-auto">
      <header className="border-border border-b px-4 py-3">
        <h2 className="text-sm font-semibold">Settings</h2>
      </header>
      <div className="mx-auto max-w-2xl space-y-8 p-4">
        <ConnectorsSection />
        <VaultSection />
        <UpdatesSection />
      </div>
    </section>
  );
}
