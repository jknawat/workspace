export function StatTile({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-surface p-5">
      <div className="text-xs font-medium uppercase tracking-wide text-ink-muted">{label}</div>
      <div className="mt-2 font-mono-num text-3xl font-semibold text-ink-primary">{value}</div>
      {sub && <div className="mt-1 text-xs text-ink-secondary">{sub}</div>}
    </div>
  );
}
