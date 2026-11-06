"use client";

import { useCallback, useEffect, useState } from "react";
import { waitForApi } from "./api";

export type ApiState = {
  phase: "waking" | "ready" | "failed";
  elapsed: number;
  error: string | null;
  lastError?: string | null;
  attempts?: number;
};

/**
 * Wakes the API once per page; exposes progress and a retry so a cold start never looks like a hang.
 * The elapsed time and the deadline run on their own one-second clock, independent of any request, so the page
 * moves on to "Try again" even if a request never settles (e.g. its timeout was delayed while the tab was hidden).
 */
export function useApiReady(budgetMs = 75000) {
  const [state, setState] = useState<ApiState>({ phase: "waking", elapsed: 0, error: null });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    const start = Date.now();
    let lastError: string | null = null;
    let attempts = 0;
    setState({ phase: "waking", elapsed: 0, error: null });
    const clock = setInterval(() => {
      if (!live) return;
      const elapsed = Math.round((Date.now() - start) / 1000);
      if (Date.now() - start > budgetMs) {
        live = false;
        clearInterval(clock);
        setState({
          phase: "failed",
          elapsed,
          lastError,
          attempts,
          error: `No answer from the analysis service after ${elapsed} seconds and ${attempts} attempt${attempts === 1 ? "" : "s"}.`,
        });
        return;
      }
      setState((s) => (s.phase === "waking" ? { ...s, elapsed, lastError, attempts } : s));
    }, 1000);
    waitForApi((_, attempt, err) => {
      attempts = attempt;
      lastError = err;
    }, budgetMs)
      .then(() => live && setState({ phase: "ready", elapsed: 0, error: null }))
      .catch((e) => live && setState({ phase: "failed", elapsed: 0, error: (e as Error).message, lastError, attempts }))
      .finally(() => {
        live = false;
        clearInterval(clock);
      });
    return () => {
      live = false;
      clearInterval(clock);
    };
  }, [tick, budgetMs]);
  const retry = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, retry };
}
