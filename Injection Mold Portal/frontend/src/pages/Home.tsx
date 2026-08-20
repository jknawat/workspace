import { Link } from "react-router-dom";
import { useI18n } from "../lib/i18n";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";

const MATERIALS = ["ABS", "Polypropylene", "Nylon PA6", "Acetal (POM)", "Polycarbonate", "PC/ABS", "HDPE", "TPU"];

export function Home() {
  const { t } = useI18n();

  const STEPS = [
    { title: t("home.step1Title"), body: t("home.step1Body") },
    { title: t("home.step2Title"), body: t("home.step2Body") },
    { title: t("home.step3Title"), body: t("home.step3Body") },
  ];

  return (
    <div>
      <section className="mx-auto max-w-6xl px-6 pb-20 pt-20 sm:pt-28">
        <div className="max-w-3xl">
          <p className="font-mono-num text-sm font-medium text-brand-blue">{t("home.tag")}</p>
          <h1 className="mt-4 font-display text-4xl font-bold tracking-tight text-ink-primary sm:text-5xl">
            {t("home.title")}
          </h1>
          <p className="mt-6 max-w-2xl text-lg text-ink-secondary">{t("home.subtitle")}</p>
          <div className="mt-8 flex flex-wrap gap-4">
            <Link to="/quote">
              <Button className="px-6 py-3 text-base">{t("home.ctaQuote")}</Button>
            </Link>
            <Link to="/resources">
              <Button variant="ghost" className="px-6 py-3 text-base">
                {t("home.ctaResources")}
              </Button>
            </Link>
          </div>
        </div>
      </section>

      <section className="border-y border-border bg-surface/40 py-14">
        <div className="mx-auto max-w-6xl px-6">
          <p className="text-center text-xs font-medium uppercase tracking-wide text-ink-muted">
            {t("home.moldingIn")}
          </p>
          <div className="mt-5 flex flex-wrap justify-center gap-x-8 gap-y-3">
            {MATERIALS.map((m) => (
              <span key={m} className="text-sm font-medium text-ink-secondary">
                {m}
              </span>
            ))}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-6 py-20">
        <h2 className="font-display text-2xl font-bold text-ink-primary">{t("home.howItWorks")}</h2>
        <div className="mt-8 grid gap-6 sm:grid-cols-3">
          {STEPS.map((step) => (
            <Card key={step.title}>
              <h3 className="font-display text-base font-semibold text-ink-primary">{step.title}</h3>
              <p className="mt-2 text-sm text-ink-secondary">{step.body}</p>
            </Card>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-6 pb-24">
        <Card className="flex flex-col items-start justify-between gap-6 bg-surface-raised p-10 sm:flex-row sm:items-center">
          <div>
            <h2 className="font-display text-2xl font-bold text-ink-primary">{t("home.readyTitle")}</h2>
            <p className="mt-2 max-w-xl text-ink-secondary">{t("home.readyBody")}</p>
          </div>
          <Link to="/quote">
            <Button className="px-6 py-3 text-base">{t("home.ctaStart")}</Button>
          </Link>
        </Card>
      </section>
    </div>
  );
}
