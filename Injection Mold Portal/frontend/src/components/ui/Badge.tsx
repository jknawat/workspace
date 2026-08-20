import type { OrderStatus } from "../../lib/types";
import { ORDER_STATUS_LABEL } from "../../lib/types";

const STATUS_STYLE: Record<OrderStatus, { dot: string; text: string }> = {
  quote_requested: { dot: "bg-ink-muted", text: "text-ink-secondary" },
  quote_sent: { dot: "bg-series-1", text: "text-ink-secondary" },
  in_tooling: { dot: "bg-status-warning", text: "text-ink-secondary" },
  in_production: { dot: "bg-status-warning", text: "text-ink-secondary" },
  quality_check: { dot: "bg-status-serious", text: "text-ink-secondary" },
  shipped: { dot: "bg-series-1", text: "text-ink-secondary" },
  delivered: { dot: "bg-status-good", text: "text-ink-secondary" },
};

export function StatusBadge({ status }: { status: OrderStatus }) {
  const style = STATUS_STYLE[status];
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${style.text}`}>
      <span className={`h-2 w-2 rounded-full ${style.dot}`} aria-hidden="true" />
      {ORDER_STATUS_LABEL[status]}
    </span>
  );
}
