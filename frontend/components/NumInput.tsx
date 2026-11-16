"use client";

import { useEffect, useRef, useState } from "react";

type Props = {
  value: number | null;
  onCommit: (v: number | null) => void;
  min?: number;
  max?: number;
  step?: number;
  /** shown value = stored value × scale (e.g. 100 for a rate stored as 0.06 and shown as 6) */
  scale?: number;
  /** an empty field means "not set" (null) instead of being restored */
  allowEmpty?: boolean;
  integer?: boolean;
  placeholder?: string;
  /** told whenever the text on screen is not a valid, applied value (half-typed, empty or out of range) */
  onPending?: (pending: boolean) => void;
  "aria-label"?: string;
};

const show = (v: number | null, scale: number) => (v === null ? "" : String(+(v * scale).toFixed(6)));

/**
 * A number field you can clear and retype. The text is yours while you type; a value is applied only when it is a
 * valid number within the limits, and leaving the field restores (or clamps) anything that is not.
 */
export default function NumInput({ value, onCommit, min, max, step, scale = 1, allowEmpty = false, integer = false, placeholder, onPending, ...rest }: Props) {
  const [text, setText] = useState(show(value, scale));
  const focused = useRef(false);
  const [invalid, setInvalid] = useState(false);

  useEffect(() => {
    if (!focused.current) setText(show(value, scale));         // outside changes (e.g. a heatmap click) show up
  }, [value, scale]);

  const parse = (t: string): number | null | undefined => {
    if (t.trim() === "") return allowEmpty ? null : undefined;
    const n = Number(t);
    if (!Number.isFinite(n) || (integer && !Number.isInteger(n))) return undefined;
    if ((min !== undefined && n < min) || (max !== undefined && n > max)) return undefined;
    return n;
  };

  return (
    <input
      type="number"
      inputMode="decimal"
      min={min}
      max={max}
      step={step}
      placeholder={placeholder}
      aria-label={rest["aria-label"]}
      aria-invalid={invalid || undefined}
      value={text}
      onFocus={() => (focused.current = true)}
      onChange={(e) => {
        setText(e.target.value);
        // text the browser cannot read as a number (a lone "-" or ".", "1e") arrives as "": it is invalid, not empty
        const n = e.target.validity.badInput ? undefined : parse(e.target.value);
        setInvalid(n === undefined);
        onPending?.(n === undefined);
        if (n !== undefined) onCommit(n === null ? null : n / scale);
      }}
      onInput={(e) => {
        // unreadable text typed into an empty field leaves the value "", so no change event reports it
        if (e.currentTarget.validity.badInput) {
          setInvalid(true);
          onPending?.(true);
        } else if (e.currentTarget.value === "" && text === "") {
          // ...and deleting that text leaves "" again, still without a change event: the field is now empty
          const n = parse("");
          setInvalid(n === undefined);
          onPending?.(n === undefined);
          if (n === null && value !== null) onCommit(null);
        }
      }}
      onBlur={(e) => {
        focused.current = false;
        const bad = e.currentTarget.validity.badInput;
        let n = bad ? undefined : parse(text);
        if (n === undefined && text.trim() !== "" && Number.isFinite(Number(text))) {
          // out of range: clamp to the nearest limit
          n = Math.min(max ?? Infinity, Math.max(min ?? -Infinity, integer ? Math.round(Number(text)) : Number(text)));
          onCommit(n / scale);
        }
        if (n === null && value !== null) onCommit(null);       // an emptied optional field means "not set"
        const restored = show(n === undefined ? value : n === null ? null : n / scale, scale);
        // unreadable text also reads as "", so React would leave it on screen when the restored text is "" too
        if (bad) e.currentTarget.value = restored;
        setText(restored);
        setInvalid(false);
        onPending?.(false);
      }}
    />
  );
}
