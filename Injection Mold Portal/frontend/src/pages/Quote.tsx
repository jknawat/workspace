import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, type CadGeometry } from "../lib/api";
import { useAuth } from "../lib/auth-context";
import type { ColorOption, Material, MaterialId, QuoteInput, QuoteResult, SurfaceFinish, ToleranceClass } from "../lib/types";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";

const DEFAULT_INPUT: QuoteInput = {
  partName: "",
  materialId: "abs",
  partWeightG: 25,
  wallThicknessMm: 2,
  quantity: 1000,
  cavities: 1,
  tolerance: "standard",
  finish: "as-molded",
  color: "natural",
  newTool: true,
  amortizeTooling: true,
};

export function Quote() {
  const { user } = useAuth();
  const navigate = useNavigate();

  const [materials, setMaterials] = useState<Material[]>([]);
  const [input, setInput] = useState<QuoteInput>(DEFAULT_INPUT);
  const [result, setResult] = useState<QuoteResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [calculating, setCalculating] = useState(false);
  const [saving, setSaving] = useState(false);

  const [cadFile, setCadFile] = useState<File | null>(null);
  const [cadGeometry, setCadGeometry] = useState<CadGeometry | null>(null);
  const [cadError, setCadError] = useState<string | null>(null);
  const [cadParsing, setCadParsing] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.materials().then(({ materials }) => setMaterials(materials));
  }, []);

  async function handleCadUpload(file: File) {
    setCadParsing(true);
    setCadError(null);
    try {
      const { geometry, estimatedWeightG } = await api.parseCad(file, input.materialId);
      setCadFile(file);
      setCadGeometry(geometry);
      update("partWeightG", estimatedWeightG);
    } catch (err) {
      setCadError(err instanceof ApiError ? err.message : "Could not parse this STL file");
      setCadFile(null);
      setCadGeometry(null);
    } finally {
      setCadParsing(false);
    }
  }

  // Re-estimate weight from the already-parsed geometry when material changes.
  useEffect(() => {
    if (!cadGeometry) return;
    const material = materials.find((m) => m.id === input.materialId);
    if (!material) return;
    update("partWeightG", Math.round(cadGeometry.volumeCm3 * material.density * 100) / 100);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [input.materialId]);

  function clearCadFile() {
    setCadFile(null);
    setCadGeometry(null);
    setCadError(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  useEffect(() => {
    const handle = setTimeout(() => {
      setCalculating(true);
      setError(null);
      api
        .quote(input)
        .then(({ result }) => setResult(result))
        .catch((err) => setError(err instanceof ApiError ? err.message : "Could not calculate a quote"))
        .finally(() => setCalculating(false));
    }, 300);
    return () => clearTimeout(handle);
  }, [input]);

  function update<K extends keyof QuoteInput>(key: K, value: QuoteInput[K]) {
    setInput((prev) => ({ ...prev, [key]: value }));
  }

  async function saveOrder() {
    if (!user) {
      navigate("/portal/login", { state: { from: { pathname: "/quote" } } });
      return;
    }
    setSaving(true);
    try {
      const { order } = await api.createOrder(input, cadFile);
      navigate(`/portal/orders/${order.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save this quote");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-14">
      <h1 className="font-display text-3xl font-bold text-ink-primary">Get an instant quote</h1>
      <p className="mt-2 max-w-2xl text-ink-secondary">
        Enter your part's spec below. The price recalculates as you type, using real
        injection-molding cost formulas — material, cycle time, machine rate and tooling.
      </p>

      <div className="mt-10 grid gap-8 lg:grid-cols-[1fr_380px]">
        <Card className="space-y-6">
          <Field label="Part name">
            <input
              className={inputClass}
              placeholder="e.g. Enclosure Lid Rev C"
              value={input.partName}
              onChange={(e) => update("partName", e.target.value)}
            />
          </Field>

          <Field label="CAD file (optional)">
            <div className="flex items-center gap-3">
              <input
                ref={fileInputRef}
                type="file"
                accept=".stl"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handleCadUpload(file);
                }}
                className="block w-full text-sm text-ink-secondary file:mr-3 file:rounded-lg file:border-0 file:bg-surface-raised file:px-3 file:py-2 file:text-sm file:font-medium file:text-ink-primary hover:file:bg-border"
              />
              {cadFile && (
                <button
                  type="button"
                  onClick={clearCadFile}
                  className="shrink-0 text-xs font-medium text-ink-muted hover:text-ink-primary"
                >
                  Remove
                </button>
              )}
            </div>
            <p className="mt-1.5 text-xs text-ink-muted">
              Upload an .stl to auto-fill part weight from real geometry (volume × material
              density). Wall thickness still needs manual entry.
            </p>
            {cadParsing && <p className="mt-2 text-xs text-brand-blue">Parsing geometry…</p>}
            {cadError && <p className="mt-2 text-xs text-status-critical">{cadError}</p>}
            {cadGeometry && !cadParsing && (
              <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 rounded-lg border border-border bg-surface-raised p-3 text-xs sm:grid-cols-4">
                <Stat label="Volume" value={`${cadGeometry.volumeCm3.toFixed(2)} cm³`} />
                <Stat label="Surface area" value={`${cadGeometry.surfaceAreaCm2.toFixed(1)} cm²`} />
                <Stat
                  label="Bounding box"
                  value={`${cadGeometry.bboxXMm.toFixed(0)}×${cadGeometry.bboxYMm.toFixed(0)}×${cadGeometry.bboxZMm.toFixed(0)} mm`}
                />
                <Stat label="Triangles" value={cadGeometry.triangleCount.toLocaleString()} />
              </div>
            )}
          </Field>

          <Field label="Material">
            <select
              className={inputClass}
              value={input.materialId}
              onChange={(e) => update("materialId", e.target.value as MaterialId)}
            >
              {materials.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
            {materials.find((m) => m.id === input.materialId) && (
              <p className="mt-1.5 text-xs text-ink-muted">
                {materials.find((m) => m.id === input.materialId)!.notes}
              </p>
            )}
          </Field>

          <div className="grid gap-6 sm:grid-cols-2">
            <Field label="Part weight (g)">
              <input
                type="number"
                min={0.1}
                step="0.1"
                className={inputClass}
                value={input.partWeightG}
                onChange={(e) => update("partWeightG", Number(e.target.value))}
              />
            </Field>
            <Field label="Nominal wall thickness (mm)">
              <input
                type="number"
                min={0.4}
                step="0.1"
                className={inputClass}
                value={input.wallThicknessMm}
                onChange={(e) => update("wallThicknessMm", Number(e.target.value))}
              />
            </Field>
            <Field label="Quantity">
              <input
                type="number"
                min={1}
                step="1"
                className={inputClass}
                value={input.quantity}
                onChange={(e) => update("quantity", Number(e.target.value))}
              />
            </Field>
            <Field label="Mold cavities">
              <input
                type="number"
                min={1}
                step="1"
                className={inputClass}
                value={input.cavities}
                onChange={(e) => update("cavities", Number(e.target.value))}
              />
            </Field>
          </div>

          <div className="grid gap-6 sm:grid-cols-3">
            <Field label="Tolerance">
              <select
                className={inputClass}
                value={input.tolerance}
                onChange={(e) => update("tolerance", e.target.value as ToleranceClass)}
              >
                <option value="standard">Standard (±0.2mm)</option>
                <option value="precision">Precision (±0.1mm)</option>
                <option value="high-precision">High-precision (±0.05mm)</option>
              </select>
            </Field>
            <Field label="Surface finish">
              <select
                className={inputClass}
                value={input.finish}
                onChange={(e) => update("finish", e.target.value as SurfaceFinish)}
              >
                <option value="as-molded">As-molded</option>
                <option value="textured">Textured</option>
                <option value="polished">Polished</option>
              </select>
            </Field>
            <Field label="Color">
              <select
                className={inputClass}
                value={input.color}
                onChange={(e) => update("color", e.target.value as ColorOption)}
              >
                <option value="natural">Natural</option>
                <option value="black">Black</option>
                <option value="custom">Custom / Pantone match</option>
              </select>
            </Field>
          </div>

          <div className="flex flex-wrap gap-6 border-t border-border pt-6">
            <label className="flex items-center gap-2 text-sm text-ink-secondary">
              <input
                type="checkbox"
                checked={input.newTool}
                onChange={(e) => update("newTool", e.target.checked)}
                className="h-4 w-4 rounded border-border-strong bg-surface-raised"
              />
              New mold/tool required
            </label>
            {input.newTool && (
              <label className="flex items-center gap-2 text-sm text-ink-secondary">
                <input
                  type="checkbox"
                  checked={input.amortizeTooling}
                  onChange={(e) => update("amortizeTooling", e.target.checked)}
                  className="h-4 w-4 rounded border-border-strong bg-surface-raised"
                />
                Amortize tooling into unit price
              </label>
            )}
          </div>
        </Card>

        <div className="lg:sticky lg:top-24 lg:self-start">
          <Card className="bg-surface-raised">
            <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">
              Estimated price
            </p>
            {error && <p className="mt-3 text-sm text-status-critical">{error}</p>}
            {result && !error && (
              <>
                <div className="mt-2 flex items-baseline gap-2">
                  <span className="font-mono-num text-4xl font-bold text-ink-primary">
                    ${result.unitPrice.toFixed(3)}
                  </span>
                  <span className="text-sm text-ink-secondary">/ part</span>
                </div>
                <p className="mt-1 font-mono-num text-sm text-ink-secondary">
                  ${result.grandTotal.toLocaleString(undefined, { maximumFractionDigits: 0 })} total
                  · {result.quantity.toLocaleString()} pcs
                </p>

                <dl className="mt-6 space-y-2 border-t border-border pt-4 text-sm">
                  {result.breakdown.map((line) => (
                    <div key={line.label} className="flex items-start justify-between gap-4">
                      <div>
                        <dt className="text-ink-secondary">{line.label}</dt>
                        {line.detail && <p className="text-xs text-ink-muted">{line.detail}</p>}
                      </div>
                      <dd className="font-mono-num shrink-0 text-ink-primary">
                        ${line.amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                      </dd>
                    </div>
                  ))}
                </dl>

                <dl className="mt-6 grid grid-cols-2 gap-4 border-t border-border pt-4 text-sm">
                  <div>
                    <dt className="text-ink-muted">Cycle time</dt>
                    <dd className="font-mono-num text-ink-primary">
                      {result.estimatedCycleTimeSec.toFixed(1)}s
                    </dd>
                  </div>
                  <div>
                    <dt className="text-ink-muted">Lead time</dt>
                    <dd className="font-mono-num text-ink-primary">
                      ~{result.estimatedLeadTimeDays} days
                    </dd>
                  </div>
                </dl>

                <Button
                  onClick={saveOrder}
                  disabled={saving || !input.partName || calculating}
                  className="mt-6 w-full"
                >
                  {saving ? "Saving…" : user ? "Save to my portal" : "Log in to save quote"}
                </Button>
              </>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

const inputClass =
  "w-full rounded-lg border border-border-strong bg-surface-raised px-3 py-2 text-sm text-ink-primary outline-none focus:border-brand-blue";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-ink-secondary">{label}</span>
      {children}
    </label>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-ink-muted">{label}</p>
      <p className="font-mono-num text-ink-primary">{value}</p>
    </div>
  );
}
