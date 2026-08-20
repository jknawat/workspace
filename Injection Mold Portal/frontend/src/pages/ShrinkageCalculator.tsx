import { useState } from "react";
import { Link } from "react-router-dom";
import { Card } from "../components/ui/Card";

interface ShrinkMaterial {
  id: string;
  name: string;
  /** midpoint mold-shrinkage rate, e.g. 0.006 = 0.6% */
  shrinkRate: number;
  range: string;
}

const MATERIALS: ShrinkMaterial[] = [
  { id: "abs", name: "ABS", shrinkRate: 0.0055, range: "0.4 – 0.7%" },
  { id: "pp", name: "Polypropylene (PP)", shrinkRate: 0.0175, range: "1.0 – 2.5%" },
  { id: "pom", name: "Acetal / POM", shrinkRate: 0.0215, range: "1.8 – 2.5%" },
  { id: "pa6", name: "Nylon PA6", shrinkRate: 0.0165, range: "0.8 – 2.5%" },
  { id: "pc", name: "Polycarbonate (PC)", shrinkRate: 0.006, range: "0.5 – 0.7%" },
  { id: "pc-abs", name: "PC/ABS Blend", shrinkRate: 0.0065, range: "0.5 – 0.8%" },
  { id: "hdpe", name: "HDPE", shrinkRate: 0.0225, range: "1.5 – 3.0%" },
  { id: "tpu", name: "TPU", shrinkRate: 0.015, range: "1.0 – 2.0%" },
];

type Direction = "cavity-to-part" | "part-to-cavity";

export function ShrinkageCalculator() {
  const [materialId, setMaterialId] = useState(MATERIALS[0].id);
  const [direction, setDirection] = useState<Direction>("part-to-cavity");
  const [dimension, setDimension] = useState(100);

  const material = MATERIALS.find((m) => m.id === materialId)!;

  const result =
    direction === "cavity-to-part"
      ? dimension * (1 - material.shrinkRate)
      : dimension / (1 - material.shrinkRate);

  return (
    <div className="mx-auto max-w-3xl px-6 py-14">
      <Link to="/resources" className="text-sm text-ink-secondary hover:text-ink-primary">
        ← Resources
      </Link>
      <h1 className="mt-2 font-display text-3xl font-bold text-ink-primary">Shrinkage calculator</h1>
      <p className="mt-2 text-ink-secondary">
        Plastic shrinks as it cools from melt temperature to room temperature. A steel mold cavity
        is always cut larger than the finished part to compensate — this tool converts between the
        two using each resin's typical mold-shrinkage rate.
      </p>

      <Card className="mt-8 space-y-6">
        <div className="flex rounded-lg border border-border-strong bg-surface-raised p-1 text-sm">
          <button
            onClick={() => setDirection("part-to-cavity")}
            className={`flex-1 rounded-md px-3 py-2 font-medium transition-colors ${
              direction === "part-to-cavity" ? "bg-brand-blue text-white" : "text-ink-secondary"
            }`}
          >
            I know the part size → cavity size
          </button>
          <button
            onClick={() => setDirection("cavity-to-part")}
            className={`flex-1 rounded-md px-3 py-2 font-medium transition-colors ${
              direction === "cavity-to-part" ? "bg-brand-blue text-white" : "text-ink-secondary"
            }`}
          >
            I know the cavity size → part size
          </button>
        </div>

        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-ink-secondary">Material</span>
          <select
            value={materialId}
            onChange={(e) => setMaterialId(e.target.value)}
            className="w-full rounded-lg border border-border-strong bg-surface-raised px-3 py-2 text-sm text-ink-primary outline-none focus:border-brand-blue"
          >
            {MATERIALS.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} — shrinkage {m.range}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-ink-secondary">
            {direction === "cavity-to-part" ? "Cavity dimension (mm)" : "Target finished part dimension (mm)"}
          </span>
          <input
            type="number"
            min={0.1}
            step="0.1"
            value={dimension}
            onChange={(e) => setDimension(Number(e.target.value))}
            className="w-full rounded-lg border border-border-strong bg-surface-raised px-3 py-2 text-sm text-ink-primary outline-none focus:border-brand-blue"
          />
        </label>

        <div className="rounded-lg border border-border bg-surface-raised p-5">
          <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">
            {direction === "cavity-to-part" ? "Expected finished part size" : "Cut the cavity at"}
          </p>
          <p className="mt-1 font-mono-num text-3xl font-bold text-ink-primary">
            {result.toFixed(3)} mm
          </p>
          <p className="mt-2 text-xs text-ink-muted">
            Using {material.name}'s midpoint shrinkage rate of {(material.shrinkRate * 100).toFixed(2)}%
            (typical range {material.range}). Actual shrinkage varies with wall thickness, fill
            pressure, and cooling time — confirm against your resin's datasheet for tight-tolerance
            features.
          </p>
        </div>
      </Card>
    </div>
  );
}
