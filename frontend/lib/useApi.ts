"use client";

import { useCallback, useEffect, useState } from "react";
import { waitForApi } from "./api";

export type ApiState = { phase: "waking" | "ready" | "failed"; elapsed: number; error: string | null };

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
          error: `No answer from the analysis service after ${elapsed} seconds. The free server may still be starting up; try again in a moment.`,
        });
        return;
      }
      setState((s) => (s.phase === "waking" ? { ...s, elapsed } : s));
    }, 1000);
    waitForApi(undefined, budgetMs)
      .then(() => live && setState({ phase: "ready", elapsed: 0, error: null }))
      .catch((e) => live && setState({ phase: "failed", elapsed: 0, error: (e as Error).message }))
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
