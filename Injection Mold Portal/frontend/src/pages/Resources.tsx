import { Link } from "react-router-dom";
import { useI18n } from "../lib/i18n";
import { Card } from "../components/ui/Card";

const MATERIAL_GUIDE = [
  { material: "ABS", wall: "1.5 – 4.0 mm", draft: "1.0° – 2.0°", shrink: "0.4 – 0.7%" },
  { material: "Polypropylene (PP)", wall: "0.8 – 3.8 mm", draft: "0.5° – 1.5°", shrink: "1.0 – 2.5%" },
  { material: "Acetal / POM", wall: "0.4 – 3.2 mm", draft: "0.5° – 1.5°", shrink: "1.8 – 2.5%" },
  { material: "Nylon PA6", wall: "0.45 – 3.0 mm", draft: "0.5° – 1.5°", shrink: "0.8 – 2.5%" },
  { material: "Polycarbonate (PC)", wall: "1.0 – 3.8 mm", draft: "1.0° – 2.0°", shrink: "0.5 – 0.7%" },
  { material: "PC/ABS Blend", wall: "1.2 – 3.5 mm", draft: "1.0° – 2.0°", shrink: "0.5 – 0.8%" },
  { material: "HDPE", wall: "0.9 – 5.0 mm", draft: "0.5° – 1.5°", shrink: "1.5 – 3.0%" },
  { material: "TPU", wall: "0.8 – 3.0 mm", draft: "2.0° – 3.5°", shrink: "1.0 – 2.0%" },
];

export function Resources() {
  const { t } = useI18n();

  const TOOLS = [
    { to: "/resources/shrinkage", title: t("resources.shrinkageTitle"), body: t("resources.shrinkageBody") },
    { to: "/resources/features", title: t("resources.featuresTitle"), body: t("resources.featuresBody") },
  ];

  const DFM_TIPS = [
    { title: t("resources.dfmTip1Title"), body: t("resources.dfmTip1Body") },
    { title: t("resources.dfmTip2Title"), body: t("resources.dfmTip2Body") },
    { title: t("resources.dfmTip3Title"), body: t("resources.dfmTip3Body") },
    { title: t("resources.dfmTip4Title"), body: t("resources.dfmTip4Body") },
    { title: t("resources.dfmTip5Title"), body: t("resources.dfmTip5Body") },
  ];

  return (
    <div className="mx-auto max-w-5xl px-6 py-14">
      <h1 className="font-display text-3xl font-bold text-ink-primary">{t("resources.title")}</h1>
      <p className="mt-2 max-w-2xl text-ink-secondary">{t("resources.subtitle")}</p>

      <section className="mt-10">
        <h2 className="font-display text-xl font-semibold text-ink-primary">{t("resources.toolsTitle")}</h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          {TOOLS.map((tool) => (
            <Link key={tool.to} to={tool.to}>
              <Card className="h-full transition-colors hover:border-border-strong">
                <h3 className="font-display text-sm font-semibold text-ink-primary">{tool.title}</h3>
                <p className="mt-2 text-sm text-ink-secondary">{tool.body}</p>
              </Card>
            </Link>
          ))}
        </div>
      </section>

      <section className="mt-14">
        <h2 className="font-display text-xl font-semibold text-ink-primary">
          {t("resources.materialGuideTitle")}
        </h2>
        <Card className="mt-4 overflow-x-auto p-0">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border text-xs uppercase tracking-wide text-ink-muted">
                <th className="px-5 py-3 font-medium">{t("resources.tableMaterial")}</th>
                <th className="px-5 py-3 font-medium">{t("resources.tableWall")}</th>
                <th className="px-5 py-3 font-medium">{t("resources.tableDraft")}</th>
                <th className="px-5 py-3 font-medium">{t("resources.tableShrink")}</th>
              </tr>
            </thead>
            <tbody>
              {MATERIAL_GUIDE.map((row, i) => (
                <tr key={row.material} className={i > 0 ? "border-t border-border" : ""}>
                  <td className="px-5 py-3 font-medium text-ink-primary">{row.material}</td>
                  <td className="px-5 py-3 font-mono-num text-ink-secondary">{row.wall}</td>
                  <td className="px-5 py-3 font-mono-num text-ink-secondary">{row.draft}</td>
                  <td className="px-5 py-3 font-mono-num text-ink-secondary">{row.shrink}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </section>

      <section className="mt-14">
        <h2 className="font-display text-xl font-semibold text-ink-primary">{t("resources.dfmTitle")}</h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          {DFM_TIPS.map((tip) => (
            <Card key={tip.title}>
              <h3 className="font-display text-sm font-semibold text-ink-primary">{tip.title}</h3>
              <p className="mt-2 text-sm text-ink-secondary">{tip.body}</p>
            </Card>
          ))}
        </div>
      </section>
    </div>
  );
}
