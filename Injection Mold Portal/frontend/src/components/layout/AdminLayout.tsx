import { Navigate } from "react-router-dom";
import { useAuth } from "../../lib/auth-context";
import { SidebarShell, type SidebarNavItem } from "./SidebarShell";

const NAV_ITEMS: SidebarNavItem[] = [
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
    <SidebarShell
      brandHref="/admin"
      brandAccent="orange"
      brandSuffix="Ops"
      subtitle="Admin console"
      navItems={NAV_ITEMS}
      userEmail={user.email}
      onLogout={logout}
      maxWidth="max-w-6xl"
    />
  );
}
