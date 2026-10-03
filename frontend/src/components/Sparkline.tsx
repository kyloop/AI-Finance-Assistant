import { Area, AreaChart, ResponsiveContainer, YAxis } from "recharts";

/** Tiny axis-less trend chart for list rows and index cards. Colour follows direction, not just the sign of today's change. */
export default function Sparkline({ data, up, height = 32 }: { data: number[]; up: boolean; height?: number }) {
  const color = up ? "var(--up)" : "var(--down)";
  const pts = data.map((v, i) => ({ i, v }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={pts} margin={{ top: 2, bottom: 2, left: 0, right: 0 }}>
        <YAxis domain={["dataMin", "dataMax"]} hide />
        <Area dataKey="v" stroke={color} fill={color} fillOpacity={0.12} strokeWidth={1.5} dot={false} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}
