import { useEffect, useState } from "react";
import { NavLink, Outlet, Link, useLocation } from "react-router-dom";
import { useAuth } from "../../lib/auth-context";
import { useI18n } from "../../lib/i18n";
import { Button } from "../ui/Button";
import { LanguageToggle } from "../ui/LanguageToggle";

export function PublicLayout() {
  const { user } = useAuth();
  const { t } = useI18n();
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();

  const NAV_LINKS = [
    { to: "/quote", label: t("nav.quote") },
    { to: "/resources", label: t("nav.resources") },
  ];

  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  return (
    <div className="flex min-h-screen flex-col bg-page">
      <header className="sticky top-0 z-40 border-b border-border bg-page/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <Link to="/" className="font-display text-lg font-bold tracking-tight text-ink-primary">
            Injection<span className="text-brand-blue">Mold</span>Portal
          </Link>
          <nav className="hidden items-center gap-8 md:flex">
            {NAV_LINKS.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                className={({ isActive }) =>
                  `text-sm font-medium transition-colors ${
                    isActive ? "text-ink-primary" : "text-ink-secondary hover:text-ink-primary"
                  }`
                }
              >
                {link.label}
              </NavLink>
            ))}
          </nav>
          <div className="flex items-center gap-3">
            <div className="hidden sm:block">
              <LanguageToggle />
            </div>
            {user ? (
              <Link to="/portal" className="hidden sm:inline-block">
                <Button variant="ghost">{t("nav.dashboard")}</Button>
              </Link>
            ) : (
              <Link to="/portal/login" className="hidden text-sm font-medium text-ink-secondary hover:text-ink-primary sm:inline">
                {t("nav.login")}
              </Link>
            )}
            <Link to="/quote" className="hidden sm:inline-block">
              <Button>{t("nav.getInstantQuote")}</Button>
            </Link>
            <button
              onClick={() => setMenuOpen((v) => !v)}
              aria-label={menuOpen ? "Close menu" : "Open menu"}
              aria-expanded={menuOpen}
              className="rounded-lg p-2 text-ink-secondary hover:bg-surface hover:text-ink-primary md:hidden"
            >
              {menuOpen ? (
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                  <path d="M5 5L15 15M15 5L5 15" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                </svg>
              ) : (
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                  <path d="M3 6H17M3 10H17M3 14H17" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                </svg>
              )}
            </button>
          </div>
        </div>

        {menuOpen && (
          <nav className="flex flex-col gap-1 border-t border-border px-6 py-4 md:hidden">
            {NAV_LINKS.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                className={({ isActive }) =>
                  `rounded-lg px-3 py-2 text-sm font-medium ${
                    isActive ? "bg-surface text-ink-primary" : "text-ink-secondary hover:bg-surface hover:text-ink-primary"
                  }`
                }
              >
                {link.label}
              </NavLink>
            ))}
            {user ? (
              <Link to="/portal" className="rounded-lg px-3 py-2 text-sm font-medium text-ink-secondary hover:bg-surface hover:text-ink-primary">
                {t("nav.dashboard")}
              </Link>
            ) : (
              <Link to="/portal/login" className="rounded-lg px-3 py-2 text-sm font-medium text-ink-secondary hover:bg-surface hover:text-ink-primary">
                {t("nav.login")}
              </Link>
            )}
            <Link to="/quote" className="mt-1">
              <Button className="w-full">{t("nav.getInstantQuote")}</Button>
            </Link>
            <div className="mt-2 flex justify-center">
              <LanguageToggle />
            </div>
          </nav>
        )}
      </header>

      <main className="flex-1">
        <Outlet />
      </main>

      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-6 py-10 text-sm text-ink-muted sm:flex-row sm:items-center sm:justify-between">
          <div>© {new Date().getFullYear()} Injection Mold Portal. {t("footer.rights")}</div>
          <div className="flex gap-6">
            <Link to="/resources" className="hover:text-ink-secondary">
              {t("footer.resources")}
            </Link>
            <Link to="/terms" className="hover:text-ink-secondary">
              {t("footer.terms")}
            </Link>
            <Link to="/privacy" className="hover:text-ink-secondary">
              {t("footer.privacy")}
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
