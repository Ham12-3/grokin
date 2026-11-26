/** Release checklist: a content security policy is set and nothing runs inline. */
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { expect, test } from "vitest";

const root = path.resolve(import.meta.dirname, "..");
const config = JSON.parse(readFileSync(path.join(root, "src-tauri/tauri.conf.json"), "utf8")) as {
  app: { security: { csp: Record<string, string> } };
  identifier: string;
};

test("the content security policy allows scripts only from the app itself", () => {
  const csp = config.app.security.csp;
  expect(csp["default-src"]).toBe("'self'");
  expect(csp["script-src"]).toBe("'self'");
  expect(JSON.stringify(csp)).not.toContain("unsafe-eval");
  expect(csp["script-src"]).not.toContain("unsafe-inline");
  // Frames are only for local previews of the user's own files.
  expect(csp["frame-src"]).toBe("blob:");
  // The app may only talk to itself and its API.
  expect(csp["connect-src"]).not.toContain("*");
});

test("the page has no inline scripts or event handlers", () => {
  const html = readFileSync(path.join(root, "index.html"), "utf8");
  const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)];
  expect(scripts).toHaveLength(1);
  expect(scripts[0][1]).toContain('src="/src/main.tsx"');
  expect(scripts[0][2].trim()).toBe("");
  expect(html).not.toMatch(/\son\w+=/);
});

test("no component injects raw HTML", () => {
  const files: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const full = path.join(dir, name);
      if (statSync(full).isDirectory()) walk(full);
      else if (/\.tsx?$/.test(name) && !name.includes(".test.")) files.push(full);
    }
  };
  walk(path.join(root, "src"));
  const offenders = files.filter((file) =>
    readFileSync(file, "utf8").includes("dangerouslySetInnerHTML"),
  );
  expect(offenders).toEqual([]);
});
