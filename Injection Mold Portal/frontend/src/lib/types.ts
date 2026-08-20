export type MaterialId = "abs" | "pp" | "pom" | "pa6" | "pc" | "pc-abs" | "hdpe" | "tpu";

export interface Material {
  id: MaterialId;
  name: string;
  density: number;
  pricePerKg: number;
  coolingFactor: number;
  notes: string;
  notesTh: string;
}

export type ToleranceClass = "standard" | "precision" | "high-precision";
export type SurfaceFinish = "as-molded" | "textured" | "polished";
export type ColorOption = "natural" | "black" | "custom";

export interface QuoteInput {
  partName: string;
  materialId: MaterialId;
  partWeightG: number;
  wallThicknessMm: number;
  quantity: number;
  cavities: number;
  tolerance: ToleranceClass;
  finish: SurfaceFinish;
  color: ColorOption;
  newTool: boolean;
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

export type OrderStatus =
  | "quote_requested"
  | "quote_sent"
  | "in_tooling"
  | "in_production"
  | "quality_check"
  | "shipped"
  | "delivered";

export type PaymentStatus = "unpaid" | "paid";

export interface CadFileSummary {
  filename: string;
  volumeCm3: number;
  surfaceAreaCm2: number;
  bboxXMm: number;
  bboxYMm: number;
  bboxZMm: number;
  triangleCount: number;
  estimatedWallThicknessMm: number | null;
}

export interface Order {
  id: string;
  userId: string;
  input: QuoteInput;
  result: QuoteResult;
  status: OrderStatus;
  paymentStatus: PaymentStatus;
  stripePaymentIntentId: string | null;
  cadFile: CadFileSummary | null;
  createdAt: string;
  updatedAt: string;
  /** present only on admin endpoints */
  customer?: { email: string; companyName: string };
}

export type UserRole = "customer" | "admin";

export interface User {
  id: string;
  email: string;
  companyName: string;
  role: UserRole;
  createdAt: string;
}

export interface Customer {
  id: string;
  email: string;
  companyName: string;
  createdAt: string;
  orderCount: number;
  totalValue: number;
}

export interface AdminStats {
  orderCount: number;
  customerCount: number;
  revenue: number;
  pipelineValue: number;
  activeProduction: number;
}

export const ORDER_STATUS_LABEL: Record<OrderStatus, string> = {
  quote_requested: "Quote requested",
  quote_sent: "Quote sent",
  in_tooling: "In tooling",
  in_production: "In production",
  quality_check: "Quality check",
  shipped: "Shipped",
  delivered: "Delivered",
};

export const ORDER_STATUS_LIST: OrderStatus[] = [
  "quote_requested",
  "quote_sent",
  "in_tooling",
  "in_production",
  "quality_check",
  "shipped",
  "delivered",
];
