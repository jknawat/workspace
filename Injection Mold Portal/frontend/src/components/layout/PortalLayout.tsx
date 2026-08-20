import { NavLink, Navigate, Outlet, Link } from "react-router-dom";
import { useAuth } from "../../lib/auth-context";

const NAV_ITEMS = [
  { to: "/portal", label: "Dashboard", end: true },
  { to: "/portal/orders", label: "Orders", end: false },
  { to: "/portal/account", label: "Account", end: false },
];

export function PortalLayout() {
  const { user, loading, logout } = useAuth();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-page text-ink-muted">
        Loading…
      </div>
    );
  }

  // No `from` state here: this guard fires both for deep-linking to a
  // protected route while logged out and for an in-app logout, and those two
  // cases shouldn't share a "return to" target — carrying it would send the
  // next login (possibly a different user) back to whichever page triggered
  // this redirect. Quote.tsx sets `from` explicitly for its one deliberate
  // "log in to save this quote" case instead.
  if (!user) {
    return <Navigate to="/portal/login" replace />;
  }

  return (
    <div className="flex min-h-screen bg-page">
      <aside className="hidden w-60 shrink-0 border-r border-border p-6 md:block">
        <Link to="/" className="font-display text-base font-bold tracking-tight text-ink-primary">
          Injection<span className="text-brand-blue">Mold</span>Portal
        </Link>
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
        <div className="mx-auto max-w-5xl">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
