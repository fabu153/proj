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
        const n = parse(e.target.value);
        setInvalid(n === undefined);
        onPending?.(n === undefined);
        if (n !== undefined) onCommit(n === null ? null : n / scale);
      }}
      onBlur={() => {
        focused.current = false;
        let n = parse(text);
        if (n === undefined && text.trim() !== "" && Number.isFinite(Number(text))) {
          // out of range: clamp to the nearest limit
          n = Math.min(max ?? Infinity, Math.max(min ?? -Infinity, integer ? Math.round(Number(text)) : Number(text)));
          onCommit(n / scale);
        }
        setText(show(n === undefined ? value : n === null ? null : n / scale, scale));
        setInvalid(false);
        onPending?.(false);
      }}
    />
  );
}
