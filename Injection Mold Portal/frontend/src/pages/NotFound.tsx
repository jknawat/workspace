import { Link } from "react-router-dom";
import { useI18n } from "../lib/i18n";
import { Button } from "../components/ui/Button";

export function NotFound() {
  const { t } = useI18n();
  return (
    <div className="mx-auto flex max-w-xl flex-col items-center px-6 py-24 text-center">
      <p className="font-mono-num text-sm font-medium text-brand-blue">404</p>
      <h1 className="mt-3 font-display text-2xl font-bold text-ink-primary">{t("notFound.title")}</h1>
      <p className="mt-2 text-ink-secondary">{t("notFound.body")}</p>
      <Link to="/" className="mt-6">
        <Button>{t("notFound.cta")}</Button>
      </Link>
    </div>
  );
}
