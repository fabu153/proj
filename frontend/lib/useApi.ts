"use client";

import { useCallback, useEffect, useState } from "react";
import { waitForApi } from "./api";

export type ApiState = { phase: "waking" | "ready" | "failed"; elapsed: number; error: string | null };

/** Wakes the API once per page; exposes progress and a retry so a cold start never looks like a hang. */
export function useApiReady() {
  const [state, setState] = useState<ApiState>({ phase: "waking", elapsed: 0, error: null });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    setState({ phase: "waking", elapsed: 0, error: null });
    waitForApi((elapsed) => live && setState((s) => (s.phase === "waking" ? { ...s, elapsed } : s)))
      .then(() => live && setState({ phase: "ready", elapsed: 0, error: null }))
      .catch((e) => live && setState({ phase: "failed", elapsed: 0, error: (e as Error).message }));
    return () => {
      live = false;
    };
  }, [tick]);
  const retry = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, retry };
}
