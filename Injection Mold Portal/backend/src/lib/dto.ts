import type { QuoteLine } from "./pricing.js";

/**
 * The DB stores an order as flat columns (+ breakdownJson). The API and
 * frontend work with the nested { input, result } shape from the pricing
 * engine — this reassembles that shape from a Prisma Order row.
 */
export function toOrderDTO(order: {
  id: string;
  userId: string;
  partName: string;
  materialId: string;
  partWeightG: number;
  wallThicknessMm: number;
  quantity: number;
  cavities: number;
  tolerance: string;
  finish: string;
  color: string;
  newTool: boolean;
  amortizeTooling: boolean;
  unitPrice: number;
  partsSubtotal: number;
  toolingCost: number;
  toolingAmortized: boolean;
  grandTotal: number;
  currency: string;
  estimatedCycleTimeSec: number;
  estimatedLeadTimeDays: number;
  breakdownJson: string;
  status: string;
  paymentStatus: string;
  stripeSessionId: string | null;
  stripePaymentIntentId: string | null;
  createdAt: Date;
  updatedAt: Date;
  cadFile?: {
    filename: string;
    volumeCm3: number;
    surfaceAreaCm2: number;
    bboxXMm: number;
    bboxYMm: number;
    bboxZMm: number;
    triangleCount: number;
  } | null;
}) {
  const breakdown: QuoteLine[] = JSON.parse(order.breakdownJson);
  return {
    id: order.id,
    userId: order.userId,
    status: order.status,
    paymentStatus: order.paymentStatus,
    stripePaymentIntentId: order.stripePaymentIntentId,
    createdAt: order.createdAt.toISOString(),
    updatedAt: order.updatedAt.toISOString(),
    cadFile: order.cadFile ?? null,
    input: {
      partName: order.partName,
      materialId: order.materialId,
      partWeightG: order.partWeightG,
      wallThicknessMm: order.wallThicknessMm,
      quantity: order.quantity,
      cavities: order.cavities,
      tolerance: order.tolerance,
      finish: order.finish,
      color: order.color,
      newTool: order.newTool,
      amortizeTooling: order.amortizeTooling,
    },
    result: {
      unitPrice: order.unitPrice,
      quantity: order.quantity,
      partsSubtotal: order.partsSubtotal,
      toolingCost: order.toolingCost,
      toolingAmortized: order.toolingAmortized,
      grandTotal: order.grandTotal,
      currency: order.currency,
      estimatedCycleTimeSec: order.estimatedCycleTimeSec,
      estimatedLeadTimeDays: order.estimatedLeadTimeDays,
      breakdown,
    },
  };
}
