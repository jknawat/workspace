import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../../lib/api";
import type { Order, OrderStatus } from "../../lib/types";
import { ORDER_STATUS_LABEL, ORDER_STATUS_LIST } from "../../lib/types";
import { Card } from "../../components/ui/Card";
import { StatusBadge } from "../../components/ui/Badge";

export function OrderDetail() {
  const { id } = useParams<{ id: string }>();
  const [order, setOrder] = useState<Order | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updating, setUpdating] = useState(false);

  useEffect(() => {
    if (!id) return;
    api
      .admin.order(id)
      .then(({ order }) => setOrder(order))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load order"));
  }, [id]);

  async function changeStatus(status: OrderStatus) {
    if (!order) return;
    setUpdating(true);
    try {
      const { order: updated } = await api.admin.updateOrderStatus(order.id, status);
      setOrder(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update status");
    } finally {
      setUpdating(false);
    }
  }

  if (error) {
    return (
      <div>
        <p className="text-sm text-status-critical">{error}</p>
        <Link to="/admin/orders" className="mt-4 inline-block text-sm text-brand-blue">
          Back to orders
        </Link>
      </div>
    );
  }

  if (!order) {
    return <p className="text-ink-muted">Loading…</p>;
  }

  return (
    <div>
      <Link to="/admin/orders" className="text-sm text-ink-secondary hover:text-ink-primary">
        ← All orders
      </Link>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-bold text-ink-primary">{order.input.partName}</h1>
          <p className="mt-1 text-sm text-ink-muted">
            {order.id} · {order.customer?.companyName} ({order.customer?.email})
          </p>
        </div>
        <StatusBadge status={order.status} />
      </div>

      <Card className="mt-6">
        <h2 className="font-display text-sm font-semibold text-ink-primary">Update status</h2>
        <div className="mt-3 flex flex-wrap gap-2">
          {ORDER_STATUS_LIST.map((s) => (
            <button
              key={s}
              disabled={updating}
              onClick={() => changeStatus(s)}
              className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50 ${
                order.status === s
                  ? "bg-brand-blue text-white"
                  : "bg-surface-raised text-ink-secondary hover:text-ink-primary"
              }`}
            >
              {ORDER_STATUS_LABEL[s]}
            </button>
          ))}
        </div>
      </Card>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Card>
          <h2 className="font-display text-sm font-semibold text-ink-primary">Part specification</h2>
          <dl className="mt-4 space-y-2 text-sm">
            <Row label="Material" value={order.input.materialId.toUpperCase()} />
            <Row label="Part weight" value={`${order.input.partWeightG} g`} />
            <Row label="Wall thickness" value={`${order.input.wallThicknessMm} mm`} />
            <Row label="Quantity" value={order.result.quantity.toLocaleString()} />
            <Row label="Cavities" value={String(order.input.cavities)} />
            <Row label="Tolerance" value={order.input.tolerance} />
            <Row label="Finish" value={order.input.finish} />
            <Row label="Color" value={order.input.color} />
            <Row label="Cycle time" value={`${order.result.estimatedCycleTimeSec.toFixed(1)}s`} />
            <Row label="Lead time" value={`~${order.result.estimatedLeadTimeDays} days`} />
          </dl>
          {order.cadFile && (
            <div className="mt-5 border-t border-border pt-4">
              <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">
                CAD file — {order.cadFile.filename}
              </p>
              <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1.5 text-sm">
                <Row label="Volume" value={`${order.cadFile.volumeCm3.toFixed(2)} cm³`} />
                <Row label="Surface area" value={`${order.cadFile.surfaceAreaCm2.toFixed(1)} cm²`} />
                <Row
                  label="Bounding box"
                  value={`${order.cadFile.bboxXMm.toFixed(0)}×${order.cadFile.bboxYMm.toFixed(0)}×${order.cadFile.bboxZMm.toFixed(0)} mm`}
                />
                <Row label="Triangles" value={order.cadFile.triangleCount.toLocaleString()} />
              </dl>
            </div>
          )}
        </Card>

        <div className="flex flex-col gap-6">
          <Card>
            <h2 className="font-display text-sm font-semibold text-ink-primary">Cost breakdown</h2>
            <dl className="mt-4 space-y-2 text-sm">
              {order.result.breakdown.map((line) => (
                <div key={line.label} className="flex items-start justify-between gap-4">
                  <div>
                    <dt className="text-ink-secondary">{line.label}</dt>
                    {line.detail && <p className="text-xs text-ink-muted">{line.detail}</p>}
                  </div>
                  <dd className="font-mono-num shrink-0 text-ink-primary">
                    ${line.amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                  </dd>
                </div>
              ))}
            </dl>
            <div className="mt-4 flex items-baseline justify-between border-t border-border pt-4">
              <span className="text-sm font-medium text-ink-primary">Total</span>
              <span className="font-mono-num text-lg font-bold text-ink-primary">
                ${order.result.grandTotal.toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </span>
            </div>
          </Card>

          <Card>
            <h2 className="font-display text-sm font-semibold text-ink-primary">Payment</h2>
            <p className="mt-2 text-sm">
              <span className={order.paymentStatus === "paid" ? "text-status-good" : "text-ink-muted"}>
                {order.paymentStatus === "paid" ? "Paid" : "Unpaid"}
              </span>
              {order.stripePaymentIntentId && (
                <span className="ml-2 font-mono-num text-xs text-ink-muted">
                  {order.stripePaymentIntentId}
                </span>
              )}
            </p>
          </Card>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-ink-secondary">{label}</dt>
      <dd className="font-mono-num text-ink-primary">{value}</dd>
    </div>
  );
}
