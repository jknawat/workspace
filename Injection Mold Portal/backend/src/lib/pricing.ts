import { MATERIALS, type MaterialId } from "../data/materials.js";

export type ToleranceClass = "standard" | "precision" | "high-precision";
export type SurfaceFinish = "as-molded" | "textured" | "polished";
export type ColorOption = "natural" | "black" | "custom";

export interface QuoteInput {
  partName: string;
  materialId: MaterialId;
  /** estimated single-part weight in grams (shot weight, excl. runner) */
  partWeightG: number;
  /** nominal wall thickness in mm, used for cycle-time estimate */
  wallThicknessMm: number;
  quantity: number;
  cavities: number;
  tolerance: ToleranceClass;
  finish: SurfaceFinish;
  color: ColorOption;
  /** whether a new mold/tool needs to be built for this job */
  newTool: boolean;
  /** if a new tool is built, spread its cost across the unit price instead of billing upfront */
  amortizeTooling: boolean;
}

export interface QuoteLine {
  label: string;
  amount: number;
  detail?: string;
}

export interface QuoteResult {
  unitPrice: number;
  quantity: number;
  partsSubtotal: number;
  toolingCost: number;
  toolingAmortized: boolean;
  grandTotal: number;
  currency: "THB";
  estimatedCycleTimeSec: number;
  estimatedLeadTimeDays: number;
  breakdown: QuoteLine[];
}

const SCRAP_RATE = 0.06; // runner/sprue + reject allowance
const FILL_TIME_S = 2;
const OPEN_CLOSE_EJECT_S = 4;
const TOLERANCE_CYCLE_ADDER_S: Record<ToleranceClass, number> = {
  standard: 0,
  precision: 2,
  "high-precision": 5,
};
const TOLERANCE_TOOL_MULTIPLIER: Record<ToleranceClass, number> = {
  standard: 1.0,
  precision: 1.4,
  "high-precision": 1.9,
};
// THB per part
const FINISH_PER_PART: Record<SurfaceFinish, number> = {
  "as-molded": 0,
  textured: 2,
  polished: 6,
};
const COLOR_PER_PART: Record<ColorOption, number> = {
  natural: 0,
  black: 0.5,
  custom: 1.5,
};
const BASE_TOOL_COST = 63_000; // THB — simple single-cavity tool, standard tolerance
const MACHINE_BASE_RATE_PER_HOUR = 1_100; // THB/hr — small press
const MACHINE_RATE_PER_CAVITY = 90; // THB/hr — larger press needed for more cavities
const LABOR_OVERHEAD_PER_PART = 1.4; // THB
const MARGIN = 0.28;
const LEAD_TIME_BASE_DAYS = 3;
const LEAD_TIME_TOOLING_DAYS = 12;

export function computeQuote(input: QuoteInput): QuoteResult {
  const material = MATERIALS[input.materialId];
  if (!material) throw new Error(`Unknown material: ${input.materialId}`);
  if (input.partWeightG <= 0) throw new Error("partWeightG must be > 0");
  if (input.wallThicknessMm <= 0) throw new Error("wallThicknessMm must be > 0");
  if (input.quantity <= 0) throw new Error("quantity must be > 0");
  if (input.cavities <= 0) throw new Error("cavities must be > 0");

  // --- cycle time (rule-of-thumb cooling model: t_cool ≈ k * wall^2) ---
  const coolingTimeS = material.coolingFactor * input.wallThicknessMm ** 2;
  const cycleTimeS =
    coolingTimeS + FILL_TIME_S + OPEN_CLOSE_EJECT_S + TOLERANCE_CYCLE_ADDER_S[input.tolerance];

  // --- material cost per part ---
  const materialCostPerPart =
    (input.partWeightG / 1000) * material.pricePerKg * (1 + SCRAP_RATE);

  // --- machine time cost per part ---
  const machineRatePerHour = MACHINE_BASE_RATE_PER_HOUR + MACHINE_RATE_PER_CAVITY * input.cavities;
  const machineCostPerPart = ((cycleTimeS / 3600) * machineRatePerHour) / input.cavities;

  // --- finish / color adders ---
  const finishCostPerPart = FINISH_PER_PART[input.finish];
  const colorCostPerPart = COLOR_PER_PART[input.color];

  const preMarginUnitCost =
    materialCostPerPart +
    machineCostPerPart +
    LABOR_OVERHEAD_PER_PART +
    finishCostPerPart +
    colorCostPerPart;

  let unitPrice = preMarginUnitCost * (1 + MARGIN);

  // --- tooling ---
  let toolingCost = 0;
  if (input.newTool) {
    const cavityMultiplier = Math.pow(input.cavities, 0.7);
    toolingCost = BASE_TOOL_COST * cavityMultiplier * TOLERANCE_TOOL_MULTIPLIER[input.tolerance];
  }

  const breakdown: QuoteLine[] = [
    {
      label: "Material",
      amount: round(materialCostPerPart * input.quantity),
      detail: `${material.name} · ${input.partWeightG} g/part incl. ${Math.round(SCRAP_RATE * 100)}% scrap allowance`,
    },
    {
      label: "Machine time",
      amount: round(machineCostPerPart * input.quantity),
      detail: `${cycleTimeS.toFixed(1)}s cycle · ${input.cavities}-cavity tool · ฿${machineRatePerHour.toFixed(0)}/hr press`,
    },
    {
      label: "Labor & overhead",
      amount: round(LABOR_OVERHEAD_PER_PART * input.quantity),
    },
  ];
  if (finishCostPerPart > 0) {
    breakdown.push({
      label: "Surface finish",
      amount: round(finishCostPerPart * input.quantity),
      detail: input.finish,
    });
  }
  if (colorCostPerPart > 0) {
    breakdown.push({
      label: "Color / masterbatch",
      amount: round(colorCostPerPart * input.quantity),
      detail: input.color,
    });
  }
  breakdown.push({
    label: "Shop margin",
    amount: round(preMarginUnitCost * MARGIN * input.quantity),
    detail: `${Math.round(MARGIN * 100)}% on material, machine time, labor & finish`,
  });

  let toolingAmortized = false;
  if (input.newTool && toolingCost > 0) {
    if (input.amortizeTooling) {
      toolingAmortized = true;
      const toolingPerPart = toolingCost / input.quantity;
      unitPrice += toolingPerPart;
      breakdown.push({
        label: "Tooling (amortized into unit price)",
        amount: round(toolingCost),
        detail: `฿${toolingPerPart.toFixed(2)}/part across ${input.quantity} units`,
      });
    } else {
      breakdown.push({
        label: "Tooling (billed upfront)",
        amount: round(toolingCost),
        detail: `${input.cavities}-cavity mold, ${input.tolerance} tolerance`,
      });
    }
  }

  const partsSubtotal = round(unitPrice * input.quantity);
  const grandTotal = round(partsSubtotal + (toolingAmortized ? 0 : toolingCost));

  const estimatedLeadTimeDays =
    LEAD_TIME_BASE_DAYS + (input.newTool ? LEAD_TIME_TOOLING_DAYS : 0) + Math.ceil(input.quantity / 5000);

  return {
    unitPrice: round(unitPrice),
    quantity: input.quantity,
    partsSubtotal,
    toolingCost: round(toolingCost),
    toolingAmortized,
    grandTotal,
    currency: "THB",
    estimatedCycleTimeSec: round(cycleTimeS),
    estimatedLeadTimeDays,
    breakdown,
  };
}

function round(n: number): number {
  return Math.round(n * 100) / 100;
}
