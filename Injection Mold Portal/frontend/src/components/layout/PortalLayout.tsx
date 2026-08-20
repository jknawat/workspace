import { Navigate } from "react-router-dom";
import { useAuth } from "../../lib/auth-context";
import { useI18n } from "../../lib/i18n";
import { SidebarShell, type SidebarNavItem } from "./SidebarShell";
import { LanguageToggle } from "../ui/LanguageToggle";

export function PortalLayout() {
  const { user, loading, logout } = useAuth();
  const { t } = useI18n();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-page text-ink-muted">
        {t("portal.loading")}
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

  const navItems: SidebarNavItem[] = [
    { to: "/portal", label: t("nav.dashboard"), end: true },
    { to: "/portal/orders", label: t("portal.ordersTitle"), end: false },
    { to: "/portal/account", label: t("portal.accountTitle"), end: false },
  ];

  return (
    <SidebarShell
      brandHref="/"
      brandAccent="blue"
      brandSuffix="Portal"
      navItems={navItems}
      userEmail={user.email}
      onLogout={logout}
      logoutLabel={t("portal.logOut")}
      maxWidth="max-w-5xl"
      headerExtra={<LanguageToggle />}
    />
  );
}
