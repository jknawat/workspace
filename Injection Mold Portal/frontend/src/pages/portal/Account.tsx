import { useAuth } from "../../lib/auth-context";
import { useI18n } from "../../lib/i18n";
import { Card } from "../../components/ui/Card";

export function Account() {
  const { user } = useAuth();
  const { t, lang } = useI18n();
  if (!user) return null;

  return (
    <div>
      <h1 className="font-display text-2xl font-bold text-ink-primary">{t("portal.accountTitle")}</h1>
      <Card className="mt-6 max-w-lg">
        <dl className="space-y-4 text-sm">
          <div>
            <dt className="text-ink-muted">{t("auth.companyName")}</dt>
            <dd className="mt-1 text-ink-primary">{user.companyName}</dd>
          </div>
          <div>
            <dt className="text-ink-muted">{t("auth.email")}</dt>
            <dd className="mt-1 text-ink-primary">{user.email}</dd>
          </div>
          <div>
            <dt className="text-ink-muted">{t("portal.memberSince")}</dt>
            <dd className="mt-1 text-ink-primary">
              {new Date(user.createdAt).toLocaleDateString(lang === "th" ? "th-TH" : undefined, {
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
