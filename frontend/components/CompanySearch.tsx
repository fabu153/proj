"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import type { SearchHit } from "@/lib/api";
import { api } from "@/lib/api";

const DEBOUNCE_MS = 250;

/**
 * Search SEC registrants by name, ticker or CIK (ARIA combobox). The request goes to this site's /api, which asks
 * SEC; the browser never calls SEC. Typing faster than the server answers is safe: only the latest reply is shown.
 */
export default function CompanySearch({ disabled = false }: { disabled?: boolean }) {
  const router = useRouter();
  const id = useId();
  const listId = `${id}-list`;
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [going, setGoing] = useState<string | null>(null);
  const seq = useRef(0);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const text = q.trim();
    const mine = ++seq.current;                       // any older reply is now stale
    if (!text) {
      setHits(null);
      setState("idle");
      setError(null);
      return;
    }
    setState("loading");
    const t = setTimeout(() => {
      api
        .searchCompanies(text)
        .then((r) => {
          if (mine !== seq.current) return;
          setHits(r.results);
          setActive(r.results.length ? 0 : -1);
          setState("done");
          setError(null);
        })
        .catch((e) => {
          if (mine !== seq.current) return;
          setHits(null);
          setError((e as Error).message);
          setState("error");
        });
    }, DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [q, retry]);

  const choose = (h: SearchHit) => {
    setGoing(h.name);
    setOpen(false);
    router.push(`/workspace?company=${h.cik}`);
  };

  const onKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    const n = hits?.length ?? 0;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      if (n) setActive((a) => (a + 1) % n);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setOpen(true);
      if (n) setActive((a) => (a <= 0 ? n - 1 : a - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (open && hits && active >= 0 && hits[active] && state === "done") choose(hits[active]);
    } else if (e.key === "Escape") {
      if (open) {
        e.preventDefault();
        setOpen(false);
      } else setQ("");
    }
  };

  const showList = open && q.trim() !== "";
  const activeId = showList && hits && active >= 0 ? `${id}-opt-${active}` : undefined;
  const announce =
    state === "loading" ? "Searching…" : state === "error" ? "" : state === "done" && hits
      ? hits.length ? `${hits.length} compan${hits.length === 1 ? "y" : "ies"} found; use the arrow keys to choose` : "No matching company"
      : "";

  return (
    <div className="company-search">
      <label htmlFor={`${id}-input`} className="search-label">Company name, ticker or CIK</label>
      <div className="search-box">
        <input
          id={`${id}-input`}
          type="search"
          role="combobox"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={activeId}
          autoComplete="off"
          spellCheck={false}
          placeholder="e.g. Patrick Industries, PATK or 76605"
          value={q}
          disabled={disabled || !!going}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={onKey}
        />
        {state === "loading" && <span className="spinner search-spinner" aria-hidden="true" />}
      </div>
      <p className="sr-only" role="status" aria-live="polite">{announce}</p>
      {going && (
        <p className="fine" role="status"><span className="spinner" aria-hidden="true" />Opening {going}: loading its SEC filings…</p>
      )}
      <div className="search-dropdown" hidden={!showList}>
        {showList && state === "loading" && !hits && <p className="search-msg">Searching SEC companies…</p>}
        {showList && state === "error" && (
          <p className="search-msg error" role="alert">
            {error}{" "}
            <button type="button" className="link" onMouseDown={(e) => e.preventDefault()} onClick={() => setRetry((r) => r + 1)}>
              Try again
            </button>
          </p>
        )}
        {showList && state === "done" && hits?.length === 0 && (
          <p className="search-msg">No U.S. SEC registrant matches “{q.trim()}”. Try the legal name, the ticker or the CIK.</p>
        )}
      <ul id={listId} role="listbox" aria-label="Matching companies" className={`search-results ${state === "loading" ? "stale" : ""}`}
        hidden={!showList || !hits?.length}>
        {showList &&
          hits?.map((h, i) => (
            <li
              key={h.cik}
              id={`${id}-opt-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : undefined}
              onMouseDown={(e) => e.preventDefault()}
              onMouseEnter={() => setActive(i)}
              onClick={() => choose(h)}
            >
              <span className="hit-name">{h.name}</span>
              <span className="hit-meta">
                {h.tickers.length ? <span className="ticker">{h.tickers.join(" · ")}</span> : null}
                <span>CIK {h.cik}</span>
                {h.exchanges.length ? <span>{h.exchanges.join(", ")}</span> : null}
                {h.curated ? <span className="badge">sample</span> : null}
              </span>
            </li>
          ))}
      </ul>
      </div>
    </div>
  );
}
