import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { formatThb } from "../../lib/currency";
import type { Order } from "../../lib/types";
import { Card } from "../../components/ui/Card";
import { StatusBadge } from "../../components/ui/Badge";
import { ErrorState } from "../../components/ui/ErrorState";

export function Orders() {
  const { t } = useI18n();
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    api
      .orders()
      .then(({ orders }) => setOrders(orders))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load orders"));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <h1 className="font-display text-2xl font-bold text-ink-primary">{t("portal.ordersTitle")}</h1>
      <p className="mt-1 text-sm text-ink-secondary">{t("portal.ordersSubtitle")}</p>

      {error ? (
        <div className="mt-6">
          <ErrorState message={error} onRetry={load} />
        </div>
      ) : !orders ? (
        <p className="mt-6 text-sm text-ink-muted">{t("portal.loadingOrders")}</p>
      ) : (
        <Card className="mt-6 overflow-x-auto p-0">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border text-xs uppercase tracking-wide text-ink-muted">
                <th className="px-5 py-3 font-medium">{t("portal.tableOrder")}</th>
                <th className="px-5 py-3 font-medium">{t("portal.tableMaterial")}</th>
                <th className="px-5 py-3 font-medium">{t("portal.tableQty")}</th>
                <th className="px-5 py-3 font-medium">{t("portal.tableTotal")}</th>
                <th className="px-5 py-3 font-medium">{t("portal.tableStatus")}</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((order, i) => (
                <tr key={order.id} className={i > 0 ? "border-t border-border" : ""}>
                  <td className="px-5 py-3">
                    <Link to={`/portal/orders/${order.id}`} className="font-medium text-ink-primary hover:text-brand-blue">
                      {order.input.partName}
                    </Link>
                    <p className="text-xs text-ink-muted">{order.id}</p>
                  </td>
                  <td className="px-5 py-3 text-ink-secondary">{order.input.materialId.toUpperCase()}</td>
                  <td className="px-5 py-3 font-mono-num text-ink-secondary">
                    {order.result.quantity.toLocaleString()}
                  </td>
                  <td className="px-5 py-3 font-mono-num text-ink-secondary">
                    {formatThb(order.result.grandTotal)}
                  </td>
                  <td className="px-5 py-3">
                    <StatusBadge status={order.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {orders.length === 0 && (
            <p className="px-5 py-8 text-center text-sm text-ink-muted">
              {t("portal.noOrdersYet")}{" "}
              <Link to="/quote" className="text-brand-blue">
                {t("portal.getFirstQuote")}
              </Link>
              .
            </p>
          )}
        </Card>
      )}
    </div>
  );
}
