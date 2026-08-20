import bcrypt from "bcryptjs";
import { prisma } from "../src/lib/prisma.js";
import { computeQuote, type QuoteInput } from "../src/lib/pricing.js";

async function main() {
  const existing = await prisma.user.findFirst();
  if (existing) {
    console.log("Database already seeded, skipping.");
    return;
  }

  const demoCustomer = await prisma.user.create({
    data: {
      email: "demo@injectionmoldportal.com",
      passwordHash: bcrypt.hashSync("demo1234", 8),
      companyName: "Acme Prototyping Co.",
      role: "customer",
      createdAt: new Date(2026, 5, 1),
    },
  });

  await prisma.user.create({
    data: {
      email: "admin@injectionmoldportal.com",
      passwordHash: bcrypt.hashSync("admin1234", 8),
      companyName: "Injection Mold Portal Ops",
      role: "admin",
      createdAt: new Date(2026, 5, 1),
    },
  });

  const seedOrders: Array<{ partName: string; qty: number; status: string; paymentStatus: string }> = [
    { partName: "Enclosure Lid Rev C", qty: 5000, status: "in_production", paymentStatus: "paid" },
    { partName: "Snap Clip Bracket", qty: 20000, status: "shipped", paymentStatus: "paid" },
    { partName: "Gearbox Housing", qty: 1200, status: "quality_check", paymentStatus: "unpaid" },
    { partName: "Cable Clip", qty: 50000, status: "delivered", paymentStatus: "paid" },
  ];

  for (const [i, s] of seedOrders.entries()) {
    const input: QuoteInput = {
      partName: s.partName,
      materialId: "abs",
      partWeightG: 12 + i * 6,
      wallThicknessMm: 2,
      quantity: s.qty,
      cavities: 4,
      tolerance: "precision",
      finish: "as-molded",
      color: "black",
      newTool: true,
      amortizeTooling: true,
    };
    const result = computeQuote(input);
    const createdDaysAgo = (seedOrders.length - i) * 6;
    const createdAt = new Date(Date.now() - createdDaysAgo * 86400000);

    await prisma.order.create({
      data: {
        userId: demoCustomer.id,
        partName: input.partName,
        materialId: input.materialId,
        partWeightG: input.partWeightG,
        wallThicknessMm: input.wallThicknessMm,
        quantity: input.quantity,
        cavities: input.cavities,
        tolerance: input.tolerance,
        finish: input.finish,
        color: input.color,
        newTool: input.newTool,
        amortizeTooling: input.amortizeTooling,
        unitPrice: result.unitPrice,
        partsSubtotal: result.partsSubtotal,
        toolingCost: result.toolingCost,
        toolingAmortized: result.toolingAmortized,
        grandTotal: result.grandTotal,
        currency: result.currency,
        estimatedCycleTimeSec: result.estimatedCycleTimeSec,
        estimatedLeadTimeDays: result.estimatedLeadTimeDays,
        breakdownJson: JSON.stringify(result.breakdown),
        status: s.status,
        paymentStatus: s.paymentStatus,
        createdAt,
        updatedAt: createdAt,
      },
    });
  }

  console.log("Seeded: demo customer, demo admin, and 4 sample orders.");
}

main()
  .catch((err) => {
    console.error(err);
    process.exit(1);
  })
  .finally(() => process.exit(0));
