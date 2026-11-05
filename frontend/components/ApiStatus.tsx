"use client";

import type { ApiState } from "@/lib/useApi";

/** Loading / error state for the API wake-up. Renders nothing once the API is ready. */
export default function ApiStatus({ state, onRetry }: { state: ApiState; onRetry: () => void }) {
  if (state.phase === "ready") return null;
  if (state.phase === "failed") {
    return (
      <div className="notice error" role="alert">
        <strong>The analysis service is not answering.</strong> {state.error}{" "}
        <button type="button" className="link" onClick={onRetry}>
          Try again
        </button>
      </div>
    );
  }
  return (
    <div className="notice calm" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" /> Connecting to the analysis service
      {state.elapsed >= 3
        ? ` (${state.elapsed}s). The free hosting sleeps when idle, so the first visit can take up to a minute.`
        : "…"}
      {state.elapsed >= 25 && (
        <>
          {" "}
          <button type="button" className="link" onClick={onRetry}>
            Try again now
          </button>
        </>
      )}
    </div>
  );
}
