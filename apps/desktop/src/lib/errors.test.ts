import type { ErrorEvent } from "@sentry/react";
import { expect, test } from "vitest";
import { scrub, startErrorReporting } from "./errors";

test("error reports carry no user content", () => {
  const event = {
    type: undefined,
    message: "failed for sam@example.com",
    user: { email: "sam@example.com" },
    extra: { draft: "my secret plan" },
    breadcrumbs: [{ message: "typed my secret plan" }],
    request: { url: "http://localhost:1420/?token=abc", headers: { Authorization: "Bearer abc" } },
    exception: {
      values: [
        {
          type: "TypeError",
          value: "cannot read my secret plan",
          stacktrace: { frames: [{ function: "send", vars: { text: "my secret plan" } }] },
        },
      ],
    },
  } as unknown as ErrorEvent;
  const cleaned = JSON.stringify(scrub(event));
  for (const leaked of ["secret plan", "sam@example.com", "Bearer", "token=abc"]) {
    expect(cleaned).not.toContain(leaked);
  }
  expect(cleaned).toContain("TypeError");
  expect(cleaned).toContain("send");
});

test("without a DSN nothing is started", () => {
  expect(startErrorReporting("0.1.0")).toBe(false);
});
