import { Navigate } from "react-router-dom";
import { useAuth } from "../../lib/auth-context";
import { SidebarShell, type SidebarNavItem } from "./SidebarShell";

const NAV_ITEMS: SidebarNavItem[] = [
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
    <SidebarShell
      brandHref="/"
      brandAccent="blue"
      brandSuffix="Portal"
      navItems={NAV_ITEMS}
      userEmail={user.email}
      onLogout={logout}
      maxWidth="max-w-5xl"
    />
  );
}
