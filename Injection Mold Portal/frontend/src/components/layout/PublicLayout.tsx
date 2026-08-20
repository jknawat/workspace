import { NavLink, Outlet, Link } from "react-router-dom";
import { useAuth } from "../../lib/auth-context";
import { Button } from "../ui/Button";

const NAV_LINKS = [
  { to: "/quote", label: "Get a Quote" },
  { to: "/resources", label: "Resources" },
];

export function PublicLayout() {
  const { user } = useAuth();

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
            {user ? (
              <Link to="/portal">
                <Button variant="ghost">Dashboard</Button>
              </Link>
            ) : (
              <>
                <Link to="/portal/login" className="hidden text-sm font-medium text-ink-secondary hover:text-ink-primary sm:inline">
                  Log in
                </Link>
                <Link to="/quote">
                  <Button>Get instant quote</Button>
                </Link>
              </>
            )}
          </div>
        </div>
      </header>

      <main className="flex-1">
        <Outlet />
      </main>

      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-6 py-10 text-sm text-ink-muted sm:flex-row sm:items-center sm:justify-between">
          <div>© {new Date().getFullYear()} Injection Mold Portal. All rights reserved.</div>
          <div className="flex gap-6">
            <Link to="/resources" className="hover:text-ink-secondary">
              Resources
            </Link>
            <Link to="/terms" className="hover:text-ink-secondary">
              Terms
            </Link>
            <Link to="/privacy" className="hover:text-ink-secondary">
              Privacy
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
