import { useState, type FormEvent } from "react";
import { useVault, useVaultActions, type VaultType } from "./api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/tauri";

const TYPES: { value: VaultType; label: string }[] = [
  { value: "api_key", label: "API key" },
  { value: "login", label: "Login" },
  { value: "card", label: "Card" },
  { value: "note", label: "Note" },
];
const TYPE_LABEL: Record<string, string> = {
  api_key: "API key",
  login: "Login",
  card: "Card",
  note: "Note",
  oauth_token: "Token",
};
const SELECT = "border-input bg-background h-9 rounded-md border px-2 text-sm";

/** Secrets your Bots can use without ever seeing them. Values are never shown again. */
export function VaultSection() {
  const vault = useVault();
  const { add, remove } = useVaultActions();
  const [name, setName] = useState("");
  const [type, setType] = useState<VaultType>("api_key");
  const [value, setValue] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim() || !value) return;
    add.mutate(
      { name: name.trim(), type, value },
      {
        onSuccess: () => {
          setName("");
          setValue(""); // gone from the app's memory as soon as it is saved
        },
      },
    );
  }

  return (
    <section aria-label="Vault" className="space-y-3">
      <header>
        <h3 className="text-sm font-semibold">Vault</h3>
        <p className="text-muted-foreground text-xs">
          A Bot uses a secret by its name, like {"{{vault:github_token}}"}. It never sees the value,
          you are asked each time one is used, and the value is never shown again.
        </p>
      </header>
      {vault.isError && (
        <p role="alert" className="text-destructive text-xs">
          {errorMessage(vault.error, "Could not load the Vault.")}
        </p>
      )}
      {vault.isSuccess && vault.data.length === 0 && (
        <p className="text-muted-foreground text-sm">Nothing in the Vault yet.</p>
      )}
      <ul aria-label="Vault items" className="space-y-1">
        {vault.data?.map((item) => (
          <li key={item.id} className="flex items-center gap-2 text-sm">
            <code className="min-w-0 flex-1 truncate">{item.name}</code>
            <span className="text-muted-foreground text-xs">{TYPE_LABEL[item.type]}</span>
            <span aria-hidden className="text-muted-foreground">
              ••••••••
            </span>
            <Button
              size="sm"
              variant="outline"
              aria-label={`Delete ${item.name}`}
              disabled={remove.isPending}
              onClick={() => remove.mutate(item.id)}
            >
              Delete
            </Button>
          </li>
        ))}
      </ul>
      <form className="grid grid-cols-[1fr_auto] gap-2" onSubmit={submit}>
        <div className="space-y-1">
          <Label htmlFor="vault-name">Name</Label>
          <Input
            id="vault-name"
            placeholder="github_token"
            autoComplete="off"
            value={name}
            onChange={(event) => setName(event.target.value.toLowerCase())}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="vault-type">Type</Label>
          <select
            id="vault-type"
            className={SELECT}
            value={type}
            onChange={(event) => setType(event.target.value as VaultType)}
          >
            {TYPES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div className="col-span-2 space-y-1">
          <Label htmlFor="vault-value">Value</Label>
          <Input
            id="vault-value"
            type="password"
            autoComplete="new-password"
            value={value}
            onChange={(event) => setValue(event.target.value)}
          />
        </div>
        <div className="col-span-2">
          <Button type="submit" size="sm" disabled={add.isPending || !name.trim() || !value}>
            Add to Vault
          </Button>
        </div>
      </form>
      {(add.error ?? remove.error) && (
        <p role="alert" className="text-destructive text-xs">
          {errorMessage(add.error ?? remove.error)}
        </p>
      )}
    </section>
  );
}
