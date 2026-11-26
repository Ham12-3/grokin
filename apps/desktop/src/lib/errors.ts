/**
 * Error reporting (Sentry). Off unless VITE_SENTRY_DSN is set at build time.
 * Reports say where the app failed, never what was typed or shown.
 */
import * as Sentry from "@sentry/react";

/** Keeps the error type and stack; drops everything that could hold user content. */
export function scrub<T extends Sentry.ErrorEvent>(event: T): T {
  delete event.user;
  delete event.extra;
  delete event.breadcrumbs;
  delete event.contexts;
  delete event.message;
  if (event.request) event.request = { url: "app://crew" };
  for (const entry of event.exception?.values ?? []) {
    entry.value = ""; // an error message can quote a chat message
    for (const frame of entry.stacktrace?.frames ?? []) delete frame.vars;
  }
  return event;
}

export function startErrorReporting(version: string): boolean {
  const dsn = import.meta.env.VITE_SENTRY_DSN as string | undefined;
  if (!dsn) return false;
  Sentry.init({
    dsn,
    release: `crew-desktop@${version}`,
    defaultIntegrations: false, // no breadcrumbs, no console or fetch capture
    integrations: [Sentry.globalHandlersIntegration(), Sentry.linkedErrorsIntegration()],
    tracesSampleRate: 0,
    beforeSend: scrub,
    beforeBreadcrumb: () => null,
  });
  return true;
}
