import { useAuth } from "../../lib/auth-context";
import { Card } from "../../components/ui/Card";

export function Account() {
  const { user } = useAuth();
  if (!user) return null;

  return (
    <div>
      <h1 className="font-display text-2xl font-bold text-ink-primary">Account</h1>
      <Card className="mt-6 max-w-lg">
        <dl className="space-y-4 text-sm">
          <div>
            <dt className="text-ink-muted">Company name</dt>
            <dd className="mt-1 text-ink-primary">{user.companyName}</dd>
          </div>
          <div>
            <dt className="text-ink-muted">Email</dt>
            <dd className="mt-1 text-ink-primary">{user.email}</dd>
          </div>
          <div>
            <dt className="text-ink-muted">Member since</dt>
            <dd className="mt-1 text-ink-primary">
              {new Date(user.createdAt).toLocaleDateString(undefined, {
                year: "numeric",
                month: "long",
                day: "numeric",
              })}
            </dd>
          </div>
        </dl>
      </Card>
    </div>
  );
}
