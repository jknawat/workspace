import { useState } from "react";
import type { Order, OrderStatus } from "../../lib/types";
import { ORDER_STATUS_LABEL } from "../../lib/types";

const PIPELINE_ORDER: OrderStatus[] = [
  "quote_requested",
  "quote_sent",
  "in_tooling",
  "in_production",
  "quality_check",
  "shipped",
  "delivered",
];

const BAR_HEIGHT = 18;
const ROW_HEIGHT = 34;
const RADIUS = 4;
const CHART_WIDTH = 420;
const LABEL_WIDTH = 110;

export function OrdersStatusChart({ orders }: { orders: Order[] }) {
  const [hovered, setHovered] = useState<OrderStatus | null>(null);

  const counts = PIPELINE_ORDER.map((status) => ({
    status,
    count: orders.filter((o) => o.status === status).length,
  })).filter((row) => row.count > 0);

  const max = Math.max(1, ...counts.map((c) => c.count));
  const plotWidth = CHART_WIDTH - LABEL_WIDTH;
  const height = counts.length * ROW_HEIGHT;

  if (counts.length === 0) {
    return <p className="text-sm text-ink-muted">No orders yet.</p>;
  }

  return (
    <svg
      viewBox={`0 0 ${CHART_WIDTH} ${height}`}
      width="100%"
      height={height}
      role="img"
      aria-label="Orders by status"
    >
      {counts.map((row, i) => {
        const y = i * ROW_HEIGHT;
        const barWidth = Math.max(4, (row.count / max) * (plotWidth - 32));
        const isHovered = hovered === row.status;
        return (
          <g
            key={row.status}
            onMouseEnter={() => setHovered(row.status)}
            onMouseLeave={() => setHovered(null)}
          >
            <rect x={0} y={y} width={CHART_WIDTH} height={ROW_HEIGHT} fill="transparent" />
            <text
              x={0}
              y={y + ROW_HEIGHT / 2}
              dominantBaseline="middle"
              className="fill-ink-secondary text-[11px]"
            >
              {ORDER_STATUS_LABEL[row.status]}
            </text>
            <path
              d={roundedRightPath(LABEL_WIDTH, y + (ROW_HEIGHT - BAR_HEIGHT) / 2, barWidth, BAR_HEIGHT, RADIUS)}
              fill="var(--color-brand-blue)"
              opacity={hovered === null || isHovered ? 1 : 0.45}
            />
            <text
              x={LABEL_WIDTH + barWidth + 8}
              y={y + ROW_HEIGHT / 2}
              dominantBaseline="middle"
              className="fill-ink-primary font-mono-num text-[11px] font-medium"
            >
              {row.count}
            </text>
            <title>
              {ORDER_STATUS_LABEL[row.status]}: {row.count} order{row.count === 1 ? "" : "s"}
            </title>
          </g>
        );
      })}
    </svg>
  );
}

function roundedRightPath(x: number, y: number, width: number, height: number, r: number): string {
  const radius = Math.min(r, width, height / 2);
  const right = x + width;
  const bottom = y + height;
  return [
    `M ${x} ${y}`,
    `H ${right - radius}`,
    `Q ${right} ${y} ${right} ${y + radius}`,
    `V ${bottom - radius}`,
    `Q ${right} ${bottom} ${right - radius} ${bottom}`,
    `H ${x}`,
    "Z",
  ].join(" ");
}
