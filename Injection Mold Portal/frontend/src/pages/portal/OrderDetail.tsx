import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../../lib/api";
import type { Order, OrderStatus } from "../../lib/types";
import { ORDER_STATUS_LABEL } from "../../lib/types";
import { Card } from "../../components/ui/Card";
import { StatusBadge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";

const PIPELINE: OrderStatus[] = [
  "quote_requested",
  "quote_sent",
  "in_tooling",
  "in_production",
  "quality_check",
  "shipped",
  "delivered",
];

export function OrderDetail() {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const paymentParam = searchParams.get("payment"); // "success" | "cancelled" | null
  const [order, setOrder] = useState<Order | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checkingOut, setCheckingOut] = useState(false);
  const [payError, setPayError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    api
      .order(id)
      .then(({ order }) => {
        if (cancelled) return;
        setOrder(order);
        // The Stripe webhook usually lands before the redirect finishes, but
        // give it one retry in case it's still in flight.
        if (paymentParam === "success" && order.paymentStatus === "unpaid") {
          setTimeout(() => {
            api.order(id).then(({ order }) => !cancelled && setOrder(order));
          }, 1500);
        }
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load order"));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function payNow() {
    if (!order) return;
    setCheckingOut(true);
    setPayError(null);
    try {
      const { checkoutUrl } = await api.checkout(order.id);
      window.location.href = checkoutUrl;
    } catch (err) {
      setPayError(err instanceof ApiError ? err.message : "Could not start checkout");
      setCheckingOut(false);
    }
  }

  if (error) {
    return (
      <div>
        <p className="text-sm text-status-critical">{error}</p>
        <Link to="/portal/orders" className="mt-4 inline-block text-sm text-brand-blue">
          Back to orders
        </Link>
      </div>
    );
  }

  if (!order) {
    return <p className="text-ink-muted">Loading…</p>;
  }

  const stepIndex = PIPELINE.indexOf(order.status);

  return (
    <div>
      <Link to="/portal/orders" className="text-sm text-ink-secondary hover:text-ink-primary">
        ← Orders
      </Link>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-bold text-ink-primary">{order.input.partName}</h1>
          <p className="mt-1 text-sm text-ink-muted">{order.id}</p>
        </div>
        <StatusBadge status={order.status} />
      </div>

      {paymentParam === "success" && order.paymentStatus === "paid" && (
        <div className="mt-4 rounded-lg border border-status-good/30 bg-status-good/10 px-4 py-3 text-sm text-ink-primary">
          Payment received — thank you.
        </div>
      )}
      {paymentParam === "cancelled" && (
        <div className="mt-4 rounded-lg border border-border bg-surface-raised px-4 py-3 text-sm text-ink-secondary">
          Checkout was cancelled. You can pay whenever you're ready.
        </div>
      )}

      <Card className="mt-6">
        <h2 className="font-display text-sm font-semibold text-ink-primary">Production pipeline</h2>
        <ol className="mt-4 flex flex-wrap gap-x-1 gap-y-3">
          {PIPELINE.map((step, i) => (
            <li key={step} className="flex items-center">
              <span
                className={`rounded-full px-3 py-1 text-xs font-medium ${
                  i <= stepIndex
                    ? "bg-brand-blue text-white"
                    : "bg-surface-raised text-ink-muted"
                }`}
              >
                {ORDER_STATUS_LABEL[step]}
              </span>
              {i < PIPELINE.length - 1 && <span className="mx-1 text-ink-muted">→</span>}
            </li>
          ))}
        </ol>
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
            <div className="flex items-center justify-between">
              <h2 className="font-display text-sm font-semibold text-ink-primary">Payment</h2>
              <span
                className={`text-xs font-medium ${order.paymentStatus === "paid" ? "text-status-good" : "text-ink-muted"}`}
              >
                {order.paymentStatus === "paid" ? "Paid" : "Unpaid"}
              </span>
            </div>
            {order.paymentStatus === "paid" ? (
              <p className="mt-3 text-sm text-ink-secondary">
                Paid in full{order.stripePaymentIntentId ? ` · ${order.stripePaymentIntentId}` : ""}.
              </p>
            ) : (
              <>
                <p className="mt-2 text-sm text-ink-secondary">
                  Pay ${order.result.grandTotal.toLocaleString(undefined, { maximumFractionDigits: 0 })} to move
                  this order into production.
                </p>
                {payError && <p className="mt-2 text-sm text-status-critical">{payError}</p>}
                <Button onClick={payNow} disabled={checkingOut} className="mt-4 w-full">
                  {checkingOut ? "Redirecting to checkout…" : "Pay now"}
                </Button>
              </>
            )}
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
