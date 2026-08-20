import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../../lib/auth-context";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";

export function Register() {
  const { user, register } = useAuth();
  const navigate = useNavigate();
  const [companyName, setCompanyName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  if (user) return <Navigate to="/portal" replace />;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await register(email, password, companyName);
      navigate("/portal", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create account");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-page px-6">
      <Card className="w-full max-w-sm">
        <h1 className="font-display text-xl font-bold text-ink-primary">Create your account</h1>
        <form onSubmit={handleSubmit} className="mt-6 space-y-4">
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-ink-secondary">Company name</span>
            <input
              required
              value={companyName}
              onChange={(e) => setCompanyName(e.target.value)}
              className="w-full rounded-lg border border-border-strong bg-surface-raised px-3 py-2 text-sm text-ink-primary outline-none focus:border-brand-blue"
            />
          </label>
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
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-border-strong bg-surface-raised px-3 py-2 text-sm text-ink-primary outline-none focus:border-brand-blue"
            />
          </label>
          {error && <p className="text-sm text-status-critical">{error}</p>}
          <Button type="submit" disabled={loading} className="w-full">
            {loading ? "Creating account…" : "Create account"}
          </Button>
        </form>
        <p className="mt-6 text-center text-sm text-ink-secondary">
          Already registered?{" "}
          <Link to="/portal/login" className="font-medium text-brand-blue">
            Log in
          </Link>
        </p>
      </Card>
    </div>
  );
}
