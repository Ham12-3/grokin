import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";
import { startErrorReporting } from "@/lib/errors";
import { appVersion } from "@/lib/tauri";

// Off unless a DSN was set at build time. Reports never include what was typed or shown.
void appVersion()
  .then(startErrorReporting)
  .catch(() => undefined);

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
