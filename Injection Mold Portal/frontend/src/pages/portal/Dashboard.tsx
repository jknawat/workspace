import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth-context";
import { useI18n } from "../../lib/i18n";
import { formatThb } from "../../lib/currency";
import type { Order } from "../../lib/types";
import { Card } from "../../components/ui/Card";
import { StatTile } from "../../components/ui/StatTile";
import { StatusBadge } from "../../components/ui/Badge";
import { ErrorState } from "../../components/ui/ErrorState";
import { OrdersStatusChart } from "../../components/charts/OrdersStatusChart";

export function Dashboard() {
  const { user } = useAuth();
  const { t } = useI18n();
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    api
      .orders()
      .then(({ orders }) => setOrders(orders))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load your dashboard"));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (error) {
    return <ErrorState message={error} onRetry={load} />;
  }

  if (!orders) {
    return <p className="text-ink-muted">{t("portal.loadingDashboard")}</p>;
  }

  const active = orders.filter((o) => o.status !== "delivered");
  const inProduction = orders.filter((o) => o.status === "in_production" || o.status === "in_tooling");
  const totalValue = orders.reduce((sum, o) => sum + o.result.grandTotal, 0);
  const avgLeadTime = orders.length
    ? Math.round(orders.reduce((sum, o) => sum + o.result.estimatedLeadTimeDays, 0) / orders.length)
    : 0;

  return (
    <div>
      <h1 className="font-display text-2xl font-bold text-ink-primary">
        {t("portal.welcomeBack", { name: user ? `, ${user.companyName}` : "" })}
      </h1>
      <p className="mt-1 text-sm text-ink-secondary">{t("portal.pipelineSub")}</p>

      <div className="mt-8 grid gap-4 sm:grid-cols-4">
        <StatTile label={t("portal.activeOrders")} value={String(active.length)} />
        <StatTile label={t("portal.inToolingProduction")} value={String(inProduction.length)} />
        <StatTile label={t("portal.portfolioValue")} value={formatThb(totalValue)} />
        <StatTile label={t("portal.avgLeadTime")} value={`${avgLeadTime}d`} />
      </div>

      <div className="mt-8 grid gap-6 lg:grid-cols-[1fr_1.4fr]">
        <Card>
          <h2 className="font-display text-sm font-semibold text-ink-primary">{t("portal.ordersByStatus")}</h2>
          <div className="mt-4">
            <OrdersStatusChart orders={orders} />
          </div>
        </Card>

        <Card className="p-0">
          <div className="flex items-center justify-between px-6 pt-6">
            <h2 className="font-display text-sm font-semibold text-ink-primary">{t("portal.recentOrders")}</h2>
            <Link to="/portal/orders" className="text-xs font-medium text-brand-blue">
              {t("portal.viewAll")}
            </Link>
          </div>
          <div className="mt-4 divide-y divide-border">
            {orders.slice(0, 5).map((order) => (
              <Link
                key={order.id}
                to={`/portal/orders/${order.id}`}
                className="flex items-center justify-between px-6 py-3 text-sm hover:bg-surface-raised"
              >
                <div>
                  <p className="font-medium text-ink-primary">{order.input.partName}</p>
                  <p className="text-xs text-ink-muted">
                    {order.id} · {order.result.quantity.toLocaleString()} {t("quote.pcs")}
                  </p>
                </div>
                <StatusBadge status={order.status} />
              </Link>
            ))}
            {orders.length === 0 && (
              <p className="px-6 py-6 text-sm text-ink-muted">
                {t("portal.noOrdersYet")}{" "}
                <Link to="/quote" className="text-brand-blue">
                  {t("portal.getQuote")}
                </Link>{" "}
                {t("portal.toGetStarted")}
              </p>
            )}
          </div>
          <div className="h-6" />
        </Card>
      </div>
    </div>
  );
}
