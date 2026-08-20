import { NavLink, Navigate, Outlet, Link } from "react-router-dom";
import { useAuth } from "../../lib/auth-context";

const NAV_ITEMS = [
  { to: "/admin", label: "Dashboard", end: true },
  { to: "/admin/orders", label: "Orders", end: false },
  { to: "/admin/customers", label: "Customers", end: false },
];

export function AdminLayout() {
  const { user, loading, logout } = useAuth();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-page text-ink-muted">
        Loading…
      </div>
    );
  }

  // See PortalLayout for why this guard doesn't carry `from` state.
  if (!user) {
    return <Navigate to="/portal/login" replace />;
  }

  if (user.role !== "admin") {
    return <Navigate to="/portal" replace />;
  }

  return (
    <div className="flex min-h-screen bg-page">
      <aside className="hidden w-60 shrink-0 border-r border-border p-6 md:block">
        <Link to="/admin" className="font-display text-base font-bold tracking-tight text-ink-primary">
          Injection<span className="text-brand-orange">Mold</span>Ops
        </Link>
        <p className="mt-1 text-xs text-ink-muted">Admin console</p>
        <nav className="mt-8 flex flex-col gap-1">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-surface text-ink-primary"
                    : "text-ink-secondary hover:bg-surface hover:text-ink-primary"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-10 border-t border-border pt-4">
          <div className="truncate text-xs text-ink-muted">{user.email}</div>
          <button
            onClick={logout}
            className="mt-2 text-sm font-medium text-ink-secondary hover:text-ink-primary"
          >
            Log out
          </button>
        </div>
      </aside>

      <main className="flex-1 px-6 py-8 md:px-10">
        <div className="mx-auto max-w-6xl">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
