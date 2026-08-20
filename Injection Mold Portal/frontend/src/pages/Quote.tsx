import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, type CadGeometry } from "../lib/api";
import { useAuth } from "../lib/auth-context";
import { useI18n } from "../lib/i18n";
import { formatThb, formatThbPrecise } from "../lib/currency";
import type { ColorOption, Material, MaterialId, QuoteInput, QuoteResult, SurfaceFinish, ToleranceClass } from "../lib/types";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";

// three.js is a heavy dependency (~850KB) only the quote page needs — split
// it into its own chunk so every other route skips downloading it.
const STLViewer = lazy(() => import("../components/ui/STLViewer").then((m) => ({ default: m.STLViewer })));

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
  const { t, lang } = useI18n();
  const navigate = useNavigate();

  const [materials, setMaterials] = useState<Material[]>([]);
  const [materialsError, setMaterialsError] = useState<string | null>(null);
  const [input, setInput] = useState<QuoteInput>(DEFAULT_INPUT);
  const [result, setResult] = useState<QuoteResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [calculating, setCalculating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const [cadFile, setCadFile] = useState<File | null>(null);
  const [cadGeometry, setCadGeometry] = useState<CadGeometry | null>(null);
  const [cadError, setCadError] = useState<string | null>(null);
  const [cadParsing, setCadParsing] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api
      .materials()
      .then(({ materials }) => setMaterials(materials))
      .catch((err) =>
        setMaterialsError(err instanceof ApiError ? err.message : "Could not load materials"),
      );
  }, []);

  async function handleCadUpload(file: File) {
    setCadParsing(true);
    setCadError(null);
    try {
      const { geometry, estimatedWeightG } = await api.parseCad(file, input.materialId);
      setCadFile(file);
      setCadGeometry(geometry);
      update("partWeightG", estimatedWeightG);
      if (geometry.estimatedWallThicknessMm !== null) {
        update("wallThicknessMm", geometry.estimatedWallThicknessMm);
      }
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

  function clearCadFile() {
    setCadFile(null);
    setCadGeometry(null);
    setCadError(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
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

  const selectedMaterial = materials.find((m) => m.id === input.materialId);

  return (
    <div className="mx-auto max-w-6xl px-6 py-14">
      <h1 className="font-display text-3xl font-bold text-ink-primary">{t("quote.title")}</h1>
      <p className="mt-2 max-w-2xl text-ink-secondary">{t("quote.subtitle")}</p>

      <div className="mt-10 grid gap-8 lg:grid-cols-[1fr_380px]">
        <div className="space-y-6">
          {/* Upload + 3D viewer */}
          <Card className="space-y-4">
            <div>
              <span className="mb-1.5 block text-sm font-medium text-ink-secondary">
                {t("quote.uploadLabel")}
              </span>
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
                    {t("quote.remove")}
                  </button>
                )}
              </div>
              <p className="mt-1.5 text-xs text-ink-muted">{t("quote.uploadHint")}</p>
              {cadParsing && <p className="mt-2 text-xs text-brand-blue">{t("quote.parsing")}</p>}
              {cadError && <p className="mt-2 text-xs text-status-critical">{cadError}</p>}
            </div>

            {cadFile ? (
              <Suspense
                fallback={
                  <div className="flex h-64 items-center justify-center rounded-lg border border-border bg-surface-raised text-sm text-ink-muted sm:h-80">
                    {t("quote.parsing")}
                  </div>
                }
              >
                <STLViewer file={cadFile} color={input.color} finish={input.finish} />
              </Suspense>
            ) : (
              <div className="flex h-64 items-center justify-center rounded-lg border border-dashed border-border-strong text-sm text-ink-muted sm:h-80">
                {t("quote.uploadFirst")}
              </div>
            )}

            {cadGeometry && !cadParsing && (
              <div className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-lg border border-border bg-surface-raised p-3 text-xs sm:grid-cols-4">
                <Stat label={t("quote.volume")} value={`${cadGeometry.volumeCm3.toFixed(2)} cm³`} />
                <Stat label={t("quote.surfaceArea")} value={`${cadGeometry.surfaceAreaCm2.toFixed(1)} cm²`} />
                <Stat
                  label={t("quote.boundingBox")}
                  value={`${cadGeometry.bboxXMm.toFixed(0)}×${cadGeometry.bboxYMm.toFixed(0)}×${cadGeometry.bboxZMm.toFixed(0)} mm`}
                />
                <Stat label={t("quote.triangles")} value={cadGeometry.triangleCount.toLocaleString()} />
              </div>
            )}
          </Card>

          {/* Primary fields */}
          <Card className="space-y-6">
            <Field label={t("quote.partNameLabel")}>
              <input
                className={inputClass}
                placeholder={t("quote.partNamePlaceholder")}
                value={input.partName}
                onChange={(e) => update("partName", e.target.value)}
              />
            </Field>

            <Field label={t("quote.materialLabel")}>
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
              {selectedMaterial && (
                <p className="mt-1.5 text-xs text-ink-muted">
                  {lang === "th" ? selectedMaterial.notesTh : selectedMaterial.notes}
                </p>
              )}
              {materialsError && <p className="mt-1.5 text-xs text-status-critical">{materialsError}</p>}
            </Field>

            <div className="grid gap-6 sm:grid-cols-2">
              <Field label={t("quote.finishLabel")}>
                <select
                  className={inputClass}
                  value={input.finish}
                  onChange={(e) => update("finish", e.target.value as SurfaceFinish)}
                >
                  <option value="as-molded">{t("quote.finishAsMolded")}</option>
                  <option value="textured">{t("quote.finishTextured")}</option>
                  <option value="polished">{t("quote.finishPolished")}</option>
                </select>
              </Field>
              <Field label={t("quote.quantityLabel")}>
                <input
                  type="number"
                  min={1}
                  step="1"
                  className={inputClass}
                  value={input.quantity}
                  onChange={(e) => update("quantity", Number(e.target.value))}
                />
              </Field>
            </div>

            {/* Weight & wall thickness: auto-detected read-only once a file is parsed, manual otherwise */}
            <div className="grid gap-6 sm:grid-cols-2">
              <Field label={t("quote.partWeightLabel")}>
                {cadFile && cadGeometry ? (
                  <ReadOnlyValue value={`${input.partWeightG.toFixed(1)} g`} tag={t("quote.autoDetected")} />
                ) : (
                  <input
                    type="number"
                    min={0.1}
                    step="0.1"
                    className={inputClass}
                    value={input.partWeightG}
                    onChange={(e) => update("partWeightG", Number(e.target.value))}
                  />
                )}
              </Field>
              <Field label={t("quote.wallThicknessLabel")}>
                {cadFile && cadGeometry?.estimatedWallThicknessMm != null ? (
                  <ReadOnlyValue value={`${input.wallThicknessMm.toFixed(2)} mm`} tag={t("quote.autoDetected")} />
                ) : (
                  <>
                    <input
                      type="number"
                      min={0.4}
                      step="0.1"
                      className={inputClass}
                      value={input.wallThicknessMm}
                      onChange={(e) => update("wallThicknessMm", Number(e.target.value))}
                    />
                    {cadFile && <p className="mt-1.5 text-xs text-status-serious">{t("quote.needsManual")}</p>}
                  </>
                )}
              </Field>
            </div>

            <div className="border-t border-border pt-4">
              <button
                type="button"
                onClick={() => setAdvancedOpen((v) => !v)}
                className="text-sm font-medium text-brand-blue hover:underline"
              >
                {advancedOpen ? t("quote.advancedHide") : t("quote.advancedShow")}
              </button>

              {advancedOpen && (
                <div className="mt-5 space-y-6">
                  <div className="grid gap-6 sm:grid-cols-3">
                    <Field label={t("quote.colorLabel")}>
                      <select
                        className={inputClass}
                        value={input.color}
                        onChange={(e) => update("color", e.target.value as ColorOption)}
                      >
                        <option value="natural">{t("quote.colorNatural")}</option>
                        <option value="black">{t("quote.colorBlack")}</option>
                        <option value="custom">{t("quote.colorCustom")}</option>
                      </select>
                    </Field>
                    <Field label={t("quote.toleranceLabel")}>
                      <select
                        className={inputClass}
                        value={input.tolerance}
                        onChange={(e) => update("tolerance", e.target.value as ToleranceClass)}
                      >
                        <option value="standard">{t("quote.toleranceStandard")}</option>
                        <option value="precision">{t("quote.tolerancePrecision")}</option>
                        <option value="high-precision">{t("quote.toleranceHighPrecision")}</option>
                      </select>
                    </Field>
                    <Field label={t("quote.cavitiesLabel")}>
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

                  <div className="flex flex-wrap gap-6">
                    <label className="flex items-center gap-2 text-sm text-ink-secondary">
                      <input
                        type="checkbox"
                        checked={input.newTool}
                        onChange={(e) => update("newTool", e.target.checked)}
                        className="h-4 w-4 rounded border-border-strong bg-surface-raised"
                      />
                      {t("quote.newToolLabel")}
                    </label>
                    {input.newTool && (
                      <label className="flex items-center gap-2 text-sm text-ink-secondary">
                        <input
                          type="checkbox"
                          checked={input.amortizeTooling}
                          onChange={(e) => update("amortizeTooling", e.target.checked)}
                          className="h-4 w-4 rounded border-border-strong bg-surface-raised"
                        />
                        {t("quote.amortizeLabel")}
                      </label>
                    )}
                  </div>
                </div>
              )}
            </div>
          </Card>
        </div>

        <div className="lg:sticky lg:top-24 lg:self-start">
          <Card className="bg-surface-raised">
            <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">{t("quote.priceTitle")}</p>
            {error && <p className="mt-3 text-sm text-status-critical">{error}</p>}
            {result && !error && (
              <>
                <div className="mt-2 flex items-baseline gap-2">
                  <span className="font-mono-num text-4xl font-bold text-ink-primary">
                    {formatThbPrecise(result.unitPrice, 2)}
                  </span>
                  <span className="text-sm text-ink-secondary">{t("quote.perPart")}</span>
                </div>
                <p className="mt-1 font-mono-num text-sm text-ink-secondary">
                  {formatThb(result.grandTotal)} {t("quote.total")} · {result.quantity.toLocaleString()} {t("quote.pcs")}
                </p>

                <dl className="mt-6 space-y-2 border-t border-border pt-4 text-sm">
                  {result.breakdown.map((line) => (
                    <div key={line.label} className="flex items-start justify-between gap-4">
                      <div>
                        <dt className="text-ink-secondary">{line.label}</dt>
                        {line.detail && <p className="text-xs text-ink-muted">{line.detail}</p>}
                      </div>
                      <dd className="font-mono-num shrink-0 text-ink-primary">
                        {formatThbPrecise(line.amount, 2)}
                      </dd>
                    </div>
                  ))}
                </dl>

                <dl className="mt-6 grid grid-cols-2 gap-4 border-t border-border pt-4 text-sm">
                  <div>
                    <dt className="text-ink-muted">{t("quote.cycleTime")}</dt>
                    <dd className="font-mono-num text-ink-primary">
                      {result.estimatedCycleTimeSec.toFixed(1)}s
                    </dd>
                  </div>
                  <div>
                    <dt className="text-ink-muted">{t("quote.leadTime")}</dt>
                    <dd className="font-mono-num text-ink-primary">
                      {t("quote.days", { n: result.estimatedLeadTimeDays })}
                    </dd>
                  </div>
                </dl>

                <Button
                  onClick={saveOrder}
                  disabled={saving || !input.partName || calculating}
                  className="mt-6 w-full"
                >
                  {saving ? t("quote.saving") : user ? t("quote.saveButton") : t("quote.loginToSave")}
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

function ReadOnlyValue({ value, tag }: { value: string; tag: string }) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-border bg-surface px-3 py-2 text-sm">
      <span className="font-mono-num text-ink-primary">{value}</span>
      <span className="rounded-full bg-brand-blue/15 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-brand-blue">
        {tag}
      </span>
    </div>
  );
}
