import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import type { AdminStats, Order } from "../../lib/types";
import { Card } from "../../components/ui/Card";
import { StatTile } from "../../components/ui/StatTile";
import { StatusBadge } from "../../components/ui/Badge";
import { OrdersStatusChart } from "../../components/charts/OrdersStatusChart";

export function Dashboard() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [orders, setOrders] = useState<Order[] | null>(null);

  useEffect(() => {
    api.admin.stats().then(setStats);
    api.admin.orders().then(({ orders }) => setOrders(orders));
  }, []);

  if (!stats || !orders) {
    return <p className="text-ink-muted">Loading dashboard…</p>;
  }

  return (
    <div>
      <h1 className="font-display text-2xl font-bold text-ink-primary">Ops dashboard</h1>
      <p className="mt-1 text-sm text-ink-secondary">Orders and revenue across every customer.</p>

      <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <StatTile label="Total orders" value={String(stats.orderCount)} />
        <StatTile label="Customers" value={String(stats.customerCount)} />
        <StatTile
          label="Revenue (paid)"
          value={`$${stats.revenue.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
        />
        <StatTile
          label="Pipeline value"
          value={`$${stats.pipelineValue.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
        />
        <StatTile label="In tooling / production" value={String(stats.activeProduction)} />
      </div>

      <div className="mt-8 grid gap-6 lg:grid-cols-[1fr_1.4fr]">
        <Card>
          <h2 className="font-display text-sm font-semibold text-ink-primary">Orders by status</h2>
          <div className="mt-4">
            <OrdersStatusChart orders={orders} />
          </div>
        </Card>

        <Card className="p-0">
          <div className="flex items-center justify-between px-6 pt-6">
            <h2 className="font-display text-sm font-semibold text-ink-primary">Recent orders</h2>
            <Link to="/admin/orders" className="text-xs font-medium text-brand-blue">
              View all
            </Link>
          </div>
          <div className="mt-4 divide-y divide-border">
            {orders.slice(0, 6).map((order) => (
              <Link
                key={order.id}
                to={`/admin/orders/${order.id}`}
                className="flex items-center justify-between px-6 py-3 text-sm hover:bg-surface-raised"
              >
                <div>
                  <p className="font-medium text-ink-primary">{order.input.partName}</p>
                  <p className="text-xs text-ink-muted">
                    {order.customer?.companyName ?? "—"} · {order.result.quantity.toLocaleString()} pcs
                  </p>
                </div>
                <StatusBadge status={order.status} />
              </Link>
            ))}
          </div>
          <div className="h-6" />
        </Card>
      </div>
    </div>
  );
}
