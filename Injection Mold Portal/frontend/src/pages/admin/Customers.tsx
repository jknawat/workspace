import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../../lib/api";
import type { Customer } from "../../lib/types";
import { Card } from "../../components/ui/Card";
import { ErrorState } from "../../components/ui/ErrorState";

export function Customers() {
  const [customers, setCustomers] = useState<Customer[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    api.admin
      .customers()
      .then(({ customers }) => setCustomers(customers))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load customers"));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <h1 className="font-display text-2xl font-bold text-ink-primary">Customers</h1>
      <p className="mt-1 text-sm text-ink-secondary">Everyone with a portal account.</p>

      {error ? (
        <div className="mt-6">
          <ErrorState message={error} onRetry={load} />
        </div>
      ) : !customers ? (
        <p className="mt-6 text-sm text-ink-muted">Loading customers…</p>
      ) : (
        <Card className="mt-6 overflow-x-auto p-0">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border text-xs uppercase tracking-wide text-ink-muted">
                <th className="px-5 py-3 font-medium">Company</th>
                <th className="px-5 py-3 font-medium">Email</th>
                <th className="px-5 py-3 font-medium">Orders</th>
                <th className="px-5 py-3 font-medium">Total value</th>
                <th className="px-5 py-3 font-medium">Since</th>
              </tr>
            </thead>
            <tbody>
              {customers.map((c, i) => (
                <tr key={c.id} className={i > 0 ? "border-t border-border" : ""}>
                  <td className="px-5 py-3 font-medium text-ink-primary">{c.companyName}</td>
                  <td className="px-5 py-3 text-ink-secondary">{c.email}</td>
                  <td className="px-5 py-3 font-mono-num text-ink-secondary">{c.orderCount}</td>
                  <td className="px-5 py-3 font-mono-num text-ink-secondary">
                    ${c.totalValue.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  </td>
                  <td className="px-5 py-3 text-ink-secondary">
                    {new Date(c.createdAt).toLocaleDateString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {customers.length === 0 && (
            <p className="px-5 py-8 text-center text-sm text-ink-muted">No customers yet.</p>
          )}
        </Card>
      )}
    </div>
  );
}
