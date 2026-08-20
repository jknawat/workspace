import { Router } from "express";
import { z } from "zod";
import { prisma } from "../lib/prisma.js";
import { toOrderDTO } from "../lib/dto.js";
import { requireAuth, requireAdmin, type AuthedRequest } from "../middleware/requireAuth.js";

export const adminRouter = Router();
adminRouter.use(requireAuth, requireAdmin);

const ORDER_STATUSES = [
  "quote_requested",
  "quote_sent",
  "in_tooling",
  "in_production",
  "quality_check",
  "shipped",
  "delivered",
] as const;

adminRouter.get("/stats", async (_req, res) => {
  const [orderCount, customerCount, orders] = await Promise.all([
    prisma.order.count(),
    prisma.user.count({ where: { role: "customer" } }),
    prisma.order.findMany({ select: { grandTotal: true, paymentStatus: true, status: true } }),
  ]);
  const revenue = orders.filter((o) => o.paymentStatus === "paid").reduce((s, o) => s + o.grandTotal, 0);
  const pipelineValue = orders
    .filter((o) => o.status !== "delivered")
    .reduce((s, o) => s + o.grandTotal, 0);
  const activeProduction = orders.filter(
    (o) => o.status === "in_tooling" || o.status === "in_production",
  ).length;

  res.json({
    orderCount,
    customerCount,
    revenue: round(revenue),
    pipelineValue: round(pipelineValue),
    activeProduction,
  });
});

adminRouter.get("/orders", async (_req, res) => {
  const rows = await prisma.order.findMany({
    include: { cadFile: true, user: { select: { email: true, companyName: true } } },
    orderBy: { createdAt: "desc" },
  });
  res.json({
    orders: rows.map((row) => ({ ...toOrderDTO(row), customer: row.user })),
  });
});

adminRouter.get("/orders/:id", async (req, res) => {
  const row = await prisma.order.findUnique({
    where: { id: (req.params.id as string) },
    include: { cadFile: true, user: { select: { email: true, companyName: true } } },
  });
  if (!row) return res.status(404).json({ error: "Order not found" });
  res.json({ order: { ...toOrderDTO(row), customer: row.user } });
});

const statusSchema = z.object({ status: z.enum(ORDER_STATUSES) });

adminRouter.patch("/orders/:id/status", async (req: AuthedRequest, res) => {
  const parsed = statusSchema.safeParse(req.body);
  if (!parsed.success) {
    return res.status(400).json({ error: "Invalid status", details: parsed.error.flatten() });
  }
  const existing = await prisma.order.findUnique({ where: { id: (req.params.id as string) } });
  if (!existing) return res.status(404).json({ error: "Order not found" });

  const updated = await prisma.order.update({
    where: { id: (req.params.id as string) },
    data: { status: parsed.data.status },
    include: { cadFile: true, user: { select: { email: true, companyName: true } } },
  });
  res.json({ order: { ...toOrderDTO(updated), customer: updated.user } });
});

adminRouter.get("/customers", async (_req, res) => {
  const customers = await prisma.user.findMany({
    where: { role: "customer" },
    include: { orders: { select: { grandTotal: true, paymentStatus: true } } },
    orderBy: { createdAt: "desc" },
  });
  res.json({
    customers: customers.map((c) => ({
      id: c.id,
      email: c.email,
      companyName: c.companyName,
      createdAt: c.createdAt,
      orderCount: c.orders.length,
      totalValue: round(c.orders.reduce((s, o) => s + o.grandTotal, 0)),
    })),
  });
});

function round(n: number): number {
  return Math.round(n * 100) / 100;
}
