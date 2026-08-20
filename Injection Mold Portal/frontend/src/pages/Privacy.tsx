import { useI18n } from "../lib/i18n";

export function Privacy() {
  const { t } = useI18n();
  return (
    <div className="mx-auto max-w-3xl px-6 py-14">
      <h1 className="font-display text-3xl font-bold text-ink-primary">{t("privacy.title")}</h1>
      <p className="mt-6 text-ink-secondary">{t("privacy.body")}</p>
    </div>
  );
}
