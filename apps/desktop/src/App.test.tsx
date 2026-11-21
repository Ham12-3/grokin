import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import App from "./App";

test("renders the empty Crew window", () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: "Crew" })).toBeInTheDocument();
});
