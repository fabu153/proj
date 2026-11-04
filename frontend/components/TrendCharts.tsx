"use client";

import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { HistoryPoint } from "@/lib/api";
import { fyLabel } from "@/lib/api";

const C = { ink: "#0e1b2c", teal: "#0f7c7a", slate: "#8c9aab", amber: "#a4650a", grid: "#e3e7ec" };
const n0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const n2 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

export default function TrendCharts({ history, upto, currency = "USD" }: { history: HistoryPoint[]; upto: string; currency?: string }) {
  const data = history
    .filter((h) => h.fiscal_year_end <= upto)
    .slice(-8)
    .map((h) => ({
      fy: fyLabel(h.fiscal_year_end),
      revenue: h.values.revenue,
      ebitda: h.metrics.ebitda,
      netLev: h.metrics.net_leverage,
      cover: h.metrics.ebitda_interest_cover,
    }));
  const axis = { fontSize: 12, fill: "#56677a" };
  return (
    <div className="chart-pair">
      <div className="sheet chart">
        <h4>Revenue and EBITDA</h4>
        <p>{currency} millions, annual. EBITDA is operating income plus D&amp;A, unadjusted.</p>
        <ResponsiveContainer width="100%" height={220}>
          <ComposedChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid stroke={C.grid} vertical={false} />
            <XAxis dataKey="fy" tick={axis} tickLine={false} axisLine={{ stroke: C.grid }} />
            <YAxis tick={axis} tickLine={false} axisLine={false} tickFormatter={(v) => n0.format(v)} width={64} />
            <Tooltip formatter={(v) => n0.format(Number(v))} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar dataKey="revenue" name="Revenue" fill={C.slate} radius={[2, 2, 0, 0]} />
            <Bar dataKey="ebitda" name="EBITDA" fill={C.teal} radius={[2, 2, 0, 0]} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="sheet chart">
        <h4>Leverage and coverage</h4>
        <p>Net debt / EBITDA (left) and EBITDA / interest (right), times. Gaps are undefined years.</p>
        <ResponsiveContainer width="100%" height={220}>
          <ComposedChart data={data} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
            <CartesianGrid stroke={C.grid} vertical={false} />
            <XAxis dataKey="fy" tick={axis} tickLine={false} axisLine={{ stroke: C.grid }} />
            <YAxis yAxisId="l" tick={axis} tickLine={false} axisLine={false} width={40} tickFormatter={(v) => `${v}x`} />
            <YAxis yAxisId="r" orientation="right" tick={axis} tickLine={false} axisLine={false} width={40} tickFormatter={(v) => `${v}x`} />
            <Tooltip formatter={(v) => `${n2.format(Number(v))}x`} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Line yAxisId="l" dataKey="netLev" name="Net debt / EBITDA" stroke={C.ink} strokeWidth={2} dot={{ r: 3 }} connectNulls={false} />
            <Line yAxisId="r" dataKey="cover" name="EBITDA / interest" stroke={C.amber} strokeWidth={2} dot={{ r: 3 }} connectNulls={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
