import { Link } from "react-router-dom";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";

const MATERIALS = ["ABS", "Polypropylene", "Nylon PA6", "Acetal (POM)", "Polycarbonate", "PC/ABS", "HDPE", "TPU"];

const STEPS = [
  {
    title: "1. Enter your part spec",
    body: "Material, weight, wall thickness, quantity, cavities and tolerance — no CAD upload required.",
  },
  {
    title: "2. Get an instant price",
    body: "Our engine runs real injection-molding cost formulas: material, cycle time, machine rate, and tooling.",
  },
  {
    title: "3. Track it in your portal",
    body: "Approve the quote and follow it through tooling, production, QC and shipping from your dashboard.",
  },
];

export function Home() {
  return (
    <div>
      <section className="mx-auto max-w-6xl px-6 pb-20 pt-20 sm:pt-28">
        <div className="max-w-3xl">
          <p className="font-mono-num text-sm font-medium text-brand-blue">
            Instant Plastic Injection Molding Quotes
          </p>
          <h1 className="mt-4 font-display text-4xl font-bold tracking-tight text-ink-primary sm:text-5xl">
            Spec your part. Get a real price in seconds.
          </h1>
          <p className="mt-6 max-w-2xl text-lg text-ink-secondary">
            No sales calls, no waiting for a manual quotation. Enter your part's material,
            geometry and volume and our pricing engine calculates material, machine time and
            tooling cost instantly — from prototype runs to production tooling.
          </p>
          <div className="mt-8 flex flex-wrap gap-4">
            <Link to="/quote">
              <Button className="px-6 py-3 text-base">Get instant quote</Button>
            </Link>
            <Link to="/resources">
              <Button variant="ghost" className="px-6 py-3 text-base">
                Design resources
              </Button>
            </Link>
          </div>
        </div>
      </section>

      <section className="border-y border-border bg-surface/40 py-14">
        <div className="mx-auto max-w-6xl px-6">
          <p className="text-center text-xs font-medium uppercase tracking-wide text-ink-muted">
            Molding in
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
        <h2 className="font-display text-2xl font-bold text-ink-primary">How it works</h2>
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
            <h2 className="font-display text-2xl font-bold text-ink-primary">
              Ready to see a real number?
            </h2>
            <p className="mt-2 max-w-xl text-ink-secondary">
              Get an engineering-based cost breakdown for your part — material, machine time and
              tooling — in under a minute.
            </p>
          </div>
          <Link to="/quote">
            <Button className="px-6 py-3 text-base">Start a quote</Button>
          </Link>
        </Card>
      </section>
    </div>
  );
}
