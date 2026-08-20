import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../../lib/auth-context";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";

function defaultDestination(role: string, location: ReturnType<typeof useLocation>): string {
  const from = (location.state as { from?: { pathname: string } })?.from?.pathname;
  if (from) return from;
  return role === "admin" ? "/admin" : "/portal";
}

export function Login() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("demo@injectionmoldportal.com");
  const [password, setPassword] = useState("demo1234");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  if (user) {
    return <Navigate to={defaultDestination(user.role, location)} replace />;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const loggedInUser = await login(email, password);
      navigate(defaultDestination(loggedInUser.role, location), { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not log in");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-page px-6">
      <Card className="w-full max-w-sm">
        <h1 className="font-display text-xl font-bold text-ink-primary">Log in to your portal</h1>
        <p className="mt-1 text-sm text-ink-secondary">
          Demo customer pre-filled — hit log in, or try{" "}
          <code className="font-mono-num text-ink-primary">admin@injectionmoldportal.com</code> /{" "}
          <code className="font-mono-num text-ink-primary">admin1234</code> for the ops console.
        </p>
        <form onSubmit={handleSubmit} className="mt-6 space-y-4">
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-ink-secondary">Email</span>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-lg border border-border-strong bg-surface-raised px-3 py-2 text-sm text-ink-primary outline-none focus:border-brand-blue"
            />
          </label>
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-ink-secondary">Password</span>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-border-strong bg-surface-raised px-3 py-2 text-sm text-ink-primary outline-none focus:border-brand-blue"
            />
          </label>
          {error && <p className="text-sm text-status-critical">{error}</p>}
          <Button type="submit" disabled={loading} className="w-full">
            {loading ? "Logging in…" : "Log in"}
          </Button>
        </form>
        <p className="mt-6 text-center text-sm text-ink-secondary">
          No account?{" "}
          <Link to="/portal/register" className="font-medium text-brand-blue">
            Register
          </Link>
        </p>
      </Card>
    </div>
  );
}
