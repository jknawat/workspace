import { useEffect, useState, type ReactNode } from "react";
import { NavLink, Outlet, Link, useLocation } from "react-router-dom";

export interface SidebarNavItem {
  to: string;
  label: string;
  end: boolean;
}

interface SidebarShellProps {
  brandHref: string;
  brandAccent: "blue" | "orange";
  brandSuffix: string;
  subtitle?: string;
  navItems: SidebarNavItem[];
  userEmail: string;
  onLogout: () => void;
  logoutLabel?: string;
  maxWidth: string;
  headerExtra?: ReactNode;
}

/** Shared sidebar-with-mobile-drawer chrome for the customer portal and admin console. */
export function SidebarShell({
  brandHref,
  brandAccent,
  brandSuffix,
  subtitle,
  navItems,
  userEmail,
  onLogout,
  logoutLabel = "Log out",
  maxWidth,
  headerExtra,
}: SidebarShellProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  const accentClass = brandAccent === "blue" ? "text-brand-blue" : "text-brand-orange";

  const brand = (
    <Link to={brandHref} className="font-display text-base font-bold tracking-tight text-ink-primary">
      Injection<span className={accentClass}>Mold</span>
      {brandSuffix}
    </Link>
  );

  const navLinks = (
    <nav className="mt-8 flex flex-col gap-1">
      {navItems.map((item) => (
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
  );

  const accountBlock = (
    <div className="mt-10 border-t border-border pt-4">
      <div className="truncate text-xs text-ink-muted">{userEmail}</div>
      <button onClick={onLogout} className="mt-2 text-sm font-medium text-ink-secondary hover:text-ink-primary">
        {logoutLabel}
      </button>
      {headerExtra && <div className="mt-4">{headerExtra}</div>}
    </div>
  );

  return (
    <div className="min-h-screen bg-page md:flex">
      {/* Mobile top bar */}
      <header className="flex items-center justify-between border-b border-border p-4 md:hidden">
        {brand}
        <button
          onClick={() => setMenuOpen((v) => !v)}
          aria-label={menuOpen ? "Close menu" : "Open menu"}
          aria-expanded={menuOpen}
          className="rounded-lg p-2 text-ink-secondary hover:bg-surface hover:text-ink-primary"
        >
          <MenuIcon open={menuOpen} />
        </button>
      </header>

      {/* Mobile drawer */}
      {menuOpen && (
        <div className="border-b border-border p-4 md:hidden">
          {subtitle && <p className="text-xs text-ink-muted">{subtitle}</p>}
          {navLinks}
          {accountBlock}
        </div>
      )}

      {/* Desktop sidebar */}
      <aside className="hidden w-60 shrink-0 border-r border-border p-6 md:block">
        {brand}
        {subtitle && <p className="mt-1 text-xs text-ink-muted">{subtitle}</p>}
        {navLinks}
        {accountBlock}
      </aside>

      <main className="flex-1 px-4 py-6 sm:px-6 sm:py-8 md:px-10">
        <div className={`mx-auto ${maxWidth}`}>
          <Outlet />
        </div>
      </main>
    </div>
  );
}

function MenuIcon({ open }: { open: boolean }): ReactNode {
  if (open) {
    return (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <path d="M5 5L15 15M15 5L5 15" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path d="M3 6H17M3 10H17M3 14H17" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}
