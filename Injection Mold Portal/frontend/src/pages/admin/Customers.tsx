import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import type { Customer } from "../../lib/types";
import { Card } from "../../components/ui/Card";

export function Customers() {
  const [customers, setCustomers] = useState<Customer[] | null>(null);

  useEffect(() => {
    api.admin.customers().then(({ customers }) => setCustomers(customers));
  }, []);

  return (
    <div>
      <h1 className="font-display text-2xl font-bold text-ink-primary">Customers</h1>
      <p className="mt-1 text-sm text-ink-secondary">Everyone with a portal account.</p>

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
            {customers?.map((c, i) => (
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
        {customers?.length === 0 && (
          <p className="px-5 py-8 text-center text-sm text-ink-muted">No customers yet.</p>
        )}
      </Card>
    </div>
  );
}
