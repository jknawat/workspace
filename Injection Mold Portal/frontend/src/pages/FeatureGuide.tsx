import { Link } from "react-router-dom";
import { useI18n } from "../lib/i18n";
import { Card } from "../components/ui/Card";

const SECTIONS = [
  {
    title: "Ribs",
    body: [
      "Ribs add stiffness without adding wall thickness. Keep rib thickness at 50–60% of the nominal wall — a full-thickness rib creates a thick section at its base that cools slower than the surrounding wall and sinks into the visible face on the opposite side.",
      "Height should stay under 3× the wall thickness per rib; taller features are better split into two shorter ribs with a gap between them.",
      "Add 0.5–1.5° of draft per side and a root radius of at least 0.25× the rib thickness to reduce stress concentration where the rib meets the wall.",
    ],
  },
  {
    title: "Bosses",
    body: [
      "A boss (for a screw or press-fit pin) follows the same thin-wall logic as ribs: outer diameter roughly 2× the screw's major diameter, wall thickness 50–60% of the part's nominal wall.",
      "Gusset the boss to the nearest wall if it's tall or load-bearing, rather than thickening the boss itself.",
      "For self-tapping screws, the inner boss diameter is typically 90% of the screw's minor diameter — check the fastener manufacturer's spec rather than guessing.",
    ],
  },
  {
    title: "Snap fits",
    body: [
      "Cantilever snap fits are the most common type: a beam deflects during assembly and springs back into an undercut. Keep the deflection strain under the material's allowable strain (check the datasheet — POM and PP tolerate far more repeated flexing than PC or ABS).",
      "Taper the beam thickness toward the tip (front 50–80% of base thickness) so stress doesn't concentrate at the fixed end.",
      "A 30–45° lead-in angle on the catch face eases assembly; a steeper (near-90°) angle on the retaining face resists accidental release.",
    ],
  },
  {
    title: "Living hinges",
    body: [
      "A living hinge is a very thin (0.2–0.5mm), short web that flexes thousands of times without failing — common in PP, less so in more brittle resins like PS or unfilled nylon.",
      "Flex the hinge immediately after molding, while the polymer chains are still oriented from flow through the thin section; letting it sit un-flexed for too long before first use increases the chance of cracking.",
      "Keep the hinge as short as the design allows (typically 0.5–1.0mm long) — a longer thin section buckles instead of flexing cleanly.",
    ],
  },
];

export function FeatureGuide() {
  const { t } = useI18n();
  return (
    <div className="mx-auto max-w-3xl px-6 py-14">
      <Link to="/resources" className="text-sm text-ink-secondary hover:text-ink-primary">
        {t("features.back")}
      </Link>
      <h1 className="mt-2 font-display text-3xl font-bold text-ink-primary">{t("features.title")}</h1>
      <p className="mt-2 text-ink-secondary">{t("features.subtitle")}</p>

      <div className="mt-8 space-y-8">
        {SECTIONS.map((section) => (
          <Card key={section.title}>
            <h2 className="font-display text-lg font-semibold text-ink-primary">{section.title}</h2>
            <div className="mt-3 space-y-2 text-sm text-ink-secondary">
              {section.body.map((p, i) => (
                <p key={i}>{p}</p>
              ))}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
