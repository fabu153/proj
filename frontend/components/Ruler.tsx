// One visual language for every "where does this number sit against a limit" question:
// the risk score against its bands, and each covenant against its threshold.

export type RulerMark = { label: string; value: number | null; color: string };
export type RulerSegment = { to: number; color: string };

type Props = {
  min: number;
  max: number;
  segments: RulerSegment[]; // ascending `to`, last should equal max
  marks: RulerMark[];
  threshold?: { value: number; label: string };
  format: (v: number) => string;
  ariaLabel: string;
};

export default function Ruler({ min, max, segments, marks, threshold, format, ariaLabel }: Props) {
  const pos = (v: number) => `${((Math.min(Math.max(v, min), max) - min) / (max - min)) * 100}%`;
  // keep labels near either end inside the track instead of clipping them
  const edge = (v: number) => {
    const f = (Math.min(Math.max(v, min), max) - min) / (max - min);
    return f < 0.08 ? { alignSelf: "flex-start" as const, transform: "translateX(-6px)" } : f > 0.92 ? { alignSelf: "flex-end" as const, transform: "translateX(6px)" } : {};
  };
  let prev = min;
  const desc = marks.map((m) => `${m.label}: ${m.value === null ? "not available" : format(m.value)}`).join("; ");
  return (
    <div>
      <div className="ruler" role="img" aria-label={`${ariaLabel}. ${desc}${threshold ? `; limit ${format(threshold.value)}` : ""}`}>
        <div className="track">
          {segments.map((s, i) => {
            const w = ((s.to - prev) / (max - min)) * 100;
            prev = s.to;
            return <div key={i} className="seg" style={{ width: `${w}%`, background: s.color }} />;
          })}
        </div>
        {threshold && (
          <>
            <div className="threshold" style={{ left: pos(threshold.value) }} />
            <div className="threshold-label" style={{ left: pos(threshold.value) }}>
              {threshold.label}
            </div>
          </>
        )}
        {marks
          .filter((m) => m.value !== null)
          .map((m) => (
            <div key={m.label} className="mark" style={{ left: pos(m.value as number) }} title={`${m.label}: ${format(m.value as number)}`}>
              <i style={{ background: m.color }} />
              {marks.length === 1 && <b style={{ color: m.color, marginTop: 2, ...edge(m.value as number) }}>{m.label}</b>}
            </div>
          ))}
      </div>
      <div className="ruler-axis num" aria-hidden="true" style={{ marginTop: marks.length > 1 ? 0 : 18 }}>
        <span>{format(min)}</span>
        <span>{format(max)}</span>
      </div>
      {marks.length > 1 && (
        <div className="ruler-legend num" aria-hidden="true">
          {marks.map((m) => (
            <span key={m.label}>
              <i style={{ background: m.color }} />
              {m.label} {m.value === null ? "n/a" : format(m.value)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
