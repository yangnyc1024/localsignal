import type { ChartPoint } from "../_utils";

type Props = {
  points: ChartPoint[];
};

export function TrendChart({ points }: Props) {
  const width = 560;
  const height = 190;
  const padding = 24;
  const maxValue = Math.max(...points.map((point) => point.value), 100);
  const minValue = Math.min(...points.map((point) => point.value), 0);
  const range = Math.max(1, maxValue - minValue);
  const coords = points.map((point, index) => {
    const x = padding + (index * (width - padding * 2)) / Math.max(1, points.length - 1);
    const y = height - padding - ((point.value - minValue) / range) * (height - padding * 2);
    return { ...point, x, y };
  });
  const path = coords.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ");
  const area = `${path} L ${coords[coords.length - 1].x} ${height - padding} L ${coords[0].x} ${height - padding} Z`;

  return (
    <div className="overflow-hidden rounded-lg border border-line bg-paper p-4">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-56 w-full" role="img" aria-label="Signal strength over recent weeks">
        <path d={area} fill="#4f6b5d" opacity="0.11" />
        <path d={path} fill="none" stroke="#4f6b5d" strokeLinecap="round" strokeLinejoin="round" strokeWidth="4" />
        {coords.map((point) => (
          <g key={point.label}>
            <circle cx={point.x} cy={point.y} r="5" fill="#4f6b5d" />
            <text x={point.x} y={height - 4} textAnchor="middle" className="fill-ink/50 text-[13px] font-semibold">
              {point.label}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}
