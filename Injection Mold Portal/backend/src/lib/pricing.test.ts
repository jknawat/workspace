import { describe, expect, it } from "vitest";
import { computeQuote, type QuoteInput } from "./pricing.js";

const BASE: QuoteInput = {
  partName: "Test Part",
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

describe("computeQuote", () => {
  it("computes a positive, internally-consistent quote", () => {
    const result = computeQuote(BASE);
    expect(result.unitPrice).toBeGreaterThan(0);
    expect(result.quantity).toBe(1000);
    expect(result.grandTotal).toBeGreaterThan(0);
    // every breakdown line should sum to roughly partsSubtotal (+ upfront tooling, if any)
    const breakdownSum = result.breakdown.reduce((s, l) => s + l.amount, 0);
    expect(breakdownSum).toBeCloseTo(result.grandTotal, 0);
  });

  it("is a known-value regression check (fails loudly if the formula changes)", () => {
    const result = computeQuote(BASE);
    expect(result.unitPrice).toBeCloseTo(2.1, 2);
    expect(result.grandTotal).toBeCloseTo(2100.95, 1);
    expect(result.estimatedCycleTimeSec).toBeCloseTo(14, 1);
  });

  it("amortized tooling: grandTotal equals partsSubtotal, tooling folded in", () => {
    const result = computeQuote({ ...BASE, amortizeTooling: true });
    expect(result.toolingAmortized).toBe(true);
    expect(result.grandTotal).toBe(result.partsSubtotal);
  });

  it("upfront tooling: grandTotal is partsSubtotal plus a separate tooling line", () => {
    const result = computeQuote({ ...BASE, amortizeTooling: false });
    expect(result.toolingAmortized).toBe(false);
    expect(result.grandTotal).toBeCloseTo(result.partsSubtotal + result.toolingCost, 2);
    // unit price should NOT carry a tooling share when billed upfront
    const amortized = computeQuote({ ...BASE, amortizeTooling: true });
    expect(result.unitPrice).toBeLessThan(amortized.unitPrice);
  });

  it("no new tool: no tooling cost at all", () => {
    const result = computeQuote({ ...BASE, newTool: false });
    expect(result.toolingCost).toBe(0);
    expect(result.toolingAmortized).toBe(false);
  });

  it("more cavities lowers machine-time cost per part (same cycle time, split more ways)", () => {
    const single = computeQuote({ ...BASE, cavities: 1, newTool: false });
    const quad = computeQuote({ ...BASE, cavities: 4, newTool: false });
    const machineLine = (r: ReturnType<typeof computeQuote>) =>
      r.breakdown.find((l) => l.label === "Machine time")!.amount;
    expect(machineLine(quad)).toBeLessThan(machineLine(single));
  });

  it("higher tolerance class costs more (slower cycle + pricier tooling)", () => {
    const standard = computeQuote({ ...BASE, tolerance: "standard" });
    const precision = computeQuote({ ...BASE, tolerance: "precision" });
    const highPrecision = computeQuote({ ...BASE, tolerance: "high-precision" });
    expect(precision.unitPrice).toBeGreaterThan(standard.unitPrice);
    expect(highPrecision.unitPrice).toBeGreaterThan(precision.unitPrice);
  });

  it("polished finish and custom color both cost more than the baseline", () => {
    const baseline = computeQuote(BASE);
    const polished = computeQuote({ ...BASE, finish: "polished" });
    const customColor = computeQuote({ ...BASE, color: "custom" });
    expect(polished.unitPrice).toBeGreaterThan(baseline.unitPrice);
    expect(customColor.unitPrice).toBeGreaterThan(baseline.unitPrice);
  });

  it("heavier parts of the same material cost more in material alone", () => {
    const light = computeQuote({ ...BASE, partWeightG: 10 });
    const heavy = computeQuote({ ...BASE, partWeightG: 100 });
    const materialLine = (r: ReturnType<typeof computeQuote>) =>
      r.breakdown.find((l) => l.label === "Material")!.amount;
    expect(materialLine(heavy)).toBeGreaterThan(materialLine(light));
  });

  it.each([
    ["partWeightG", { partWeightG: 0 }],
    ["partWeightG negative", { partWeightG: -5 }],
    ["wallThicknessMm", { wallThicknessMm: 0 }],
    ["quantity", { quantity: 0 }],
    ["cavities", { cavities: 0 }],
  ] as const)("rejects invalid %s", (_label, overrides) => {
    expect(() => computeQuote({ ...BASE, ...overrides })).toThrow();
  });

  it("rejects an unknown material", () => {
    expect(() => computeQuote({ ...BASE, materialId: "unobtainium" as never })).toThrow();
  });
});
