import { expect, test } from "vitest";
import { isOlder } from "./version";

test("versions compare by number, not by text", () => {
  expect(isOlder("0.1.0", "0.1.0")).toBe(false);
  expect(isOlder("0.1.9", "0.1.10")).toBe(true);
  expect(isOlder("0.2.0", "0.1.10")).toBe(false);
  expect(isOlder("0.1", "0.1.1")).toBe(true);
  expect(isOlder("1.0.0-beta", "1.0.0")).toBe(false);
  expect(isOlder("0.9.9", "1.0.0")).toBe(true);
});
