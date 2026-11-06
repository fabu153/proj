"use client";

import { API_URL } from "@/lib/api";
import type { ApiState } from "@/lib/useApi";

/** Turns the browser's error into what the user can do about it. */
function diagnosis(err: string | null | undefined) {
  if (!err) return null;
  if (/failed to fetch|networkerror|load failed|network request failed/i.test(err)) {
    return "Your browser could not reach the service at all. A browser extension (ad or tracker blocker, privacy shield), a school or company network filter, or a VPN is the usual cause.";
  }
  if (/did not answer within/i.test(err)) {
    return "The service is reachable but slow to respond, which usually means the free server is still starting.";
  }
  return null;
}

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
        {state.lastError && <div className="fine" style={{ marginTop: 6 }}>Last error from your browser: {state.lastError}</div>}
        {diagnosis(state.lastError) && <div style={{ marginTop: 6 }}>{diagnosis(state.lastError)}</div>}
        <div className="fine" style={{ marginTop: 6 }}>
          To check, open{" "}
          <a href={`${API_URL}/health`} target="_blank" rel="noreferrer">
            the service&apos;s health check
          </a>{" "}
          in a new tab. If it shows <code>&quot;status&quot;:&quot;ok&quot;</code>, the server works and something in this browser is
          blocking the page&apos;s requests: try a private window with extensions off, or another browser. If it does not load, your
          network cannot reach the service: try another network or a phone hotspot.
        </div>
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
