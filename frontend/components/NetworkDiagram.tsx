/** The deployed network, drawn from its frozen architecture: 62 -> 128 -> 64 -> 32 -> 1, five seeds averaged, then Platt-calibrated. */
export default function NetworkDiagram() {
  const layers = [
    { n: 62, dots: 9, title: "Input 62", lines: ["31 ratios and trends", "+ 31 missing-value flags"] },
    { n: 128, dots: 12, title: "Dense 128", lines: ["ReLU, LayerNorm", "dropout 0.25"] },
    { n: 64, dots: 8, title: "Dense 64", lines: ["ReLU", "dropout 0.20"] },
    { n: 32, dots: 5, title: "Dense 32", lines: ["ReLU"] },
    { n: 1, dots: 1, title: "Output 1", lines: ["stress logit"] },
  ];
  const W = 780, H = 270, top = 22, span = 168;
  const xs = layers.map((_, i) => 46 + i * 128);
  const ys = (k: number) => Array.from({ length: k }, (_, j) => top + (k === 1 ? span / 2 : (j * span) / (k - 1)));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-labelledby="nn-title nn-desc" className="nn-diagram">
      <title id="nn-title">Network architecture</title>
      <desc id="nn-desc">
        A feed-forward network: 62 inputs, hidden layers of 128, 64 and 32 units, one output logit. Five copies trained with different seeds
        are averaged, then Platt scaling turns the average logit into a probability.
      </desc>
      {layers.slice(0, -1).map((l, i) =>
        ys(l.dots).flatMap((y1, a) =>
          ys(layers[i + 1].dots).map((y2, b) => (
            <line key={`${i}-${a}-${b}`} x1={xs[i]} y1={y1} x2={xs[i + 1]} y2={y2} stroke="#c9d1da" strokeWidth={0.6} />
          )),
        ),
      )}
      {layers.map((l, i) => (
        <g key={l.title}>
          {ys(l.dots).map((y, j) => (
            <circle key={j} cx={xs[i]} cy={y} r={i === 4 ? 9 : 6} fill={i === 0 ? "#e1f0ef" : i === 4 ? "#0e1b2c" : "#fff"} stroke="#0e1b2c" strokeWidth={1.2} />
          ))}
          <text x={xs[i]} y={top + span + 28} textAnchor="middle" fontSize="13" fontWeight="600" fill="#15212f">{l.title}</text>
          {l.lines.map((t, k) => (
            <text key={k} x={xs[i]} y={top + span + 45 + k * 15} textAnchor="middle" fontSize="11.5" fill="#56677a">{t}</text>
          ))}
        </g>
      ))}
      <g>
        <line x1={xs[4] + 14} y1={top + span / 2} x2={xs[4] + 52} y2={top + span / 2} stroke="#0e1b2c" strokeWidth={1.4} markerEnd="url(#arr)" />
        <rect x={xs[4] + 56} y={top + span / 2 - 42} width={150} height={84} rx={5} fill="#fafbfa" stroke="#b7c0cb" />
        <text x={xs[4] + 131} y={top + span / 2 - 20} textAnchor="middle" fontSize="12" fontWeight="600" fill="#15212f">× 5 seeds, averaged</text>
        <text x={xs[4] + 131} y={top + span / 2 + 1} textAnchor="middle" fontSize="12" fill="#15212f">Platt calibration</text>
        <text x={xs[4] + 131} y={top + span / 2 + 22} textAnchor="middle" fontSize="12" fill="#0f7c7a" fontWeight="600">→ probability</text>
      </g>
      <defs>
        <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0,0 L10,5 L0,10 z" fill="#0e1b2c" />
        </marker>
      </defs>
    </svg>
  );
}
