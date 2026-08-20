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

const DFM_TIPS = [
  {
    title: "Keep walls uniform",
    body: "Sudden thickness changes cause sink marks and warping. Transition gradually — no more than a 25% step between adjacent walls.",
  },
  {
    title: "Always add draft",
    body: "Every vertical face needs draft to release from the mold without scuffing. Textured surfaces need extra draft (roughly +1° per 0.025mm of texture depth).",
  },
  {
    title: "Design ribs at 50–60% of wall thickness",
    body: "Full-thickness ribs sink into the visible face on the opposite side. Keep rib thickness at 50–60% of the nominal wall.",
  },
  {
    title: "Round internal and external corners",
    body: "Sharp corners concentrate stress and slow filling. A radius of at least 25% of the wall thickness reduces stress risers significantly.",
  },
  {
    title: "Plan cavitation early",
    body: "Cavity count changes the tool cost, cycle economics and achievable tolerance — decide it before finalizing part geometry, not after.",
  },
];

export function Resources() {
  return (
    <div className="mx-auto max-w-5xl px-6 py-14">
      <h1 className="font-display text-3xl font-bold text-ink-primary">Design resources</h1>
      <p className="mt-2 max-w-2xl text-ink-secondary">
        Reference data and design-for-manufacturability guidelines for plastic injection molded
        parts. Typical ranges — always confirm with your specific resin's datasheet.
      </p>

      <section className="mt-10">
        <h2 className="font-display text-xl font-semibold text-ink-primary">
          Material guide: wall thickness, draft angle & shrinkage
        </h2>
        <Card className="mt-4 overflow-x-auto p-0">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border text-xs uppercase tracking-wide text-ink-muted">
                <th className="px-5 py-3 font-medium">Material</th>
                <th className="px-5 py-3 font-medium">Recommended wall</th>
                <th className="px-5 py-3 font-medium">Draft angle</th>
                <th className="px-5 py-3 font-medium">Mold shrinkage</th>
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
        <h2 className="font-display text-xl font-semibold text-ink-primary">
          Design-for-manufacturability checklist
        </h2>
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
