import { Router } from "express";
import multer from "multer";
import { z } from "zod";
import { randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { prisma } from "../lib/prisma.js";
import { computeQuote } from "../lib/pricing.js";
import { toOrderDTO } from "../lib/dto.js";
import { parseStl } from "../lib/stl-parser.js";
import { MATERIALS } from "../data/materials.js";
import { requireAuth, type AuthedRequest } from "../middleware/requireAuth.js";

export const ordersRouter = Router();
ordersRouter.use(requireAuth);

const UPLOAD_DIR = path.resolve(process.cwd(), "uploads");
const upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: 25 * 1024 * 1024 } });

ordersRouter.get("/", async (req: AuthedRequest, res) => {
  const rows = await prisma.order.findMany({
    where: { userId: req.userId },
    include: { cadFile: true },
    orderBy: { createdAt: "desc" },
  });
  res.json({ orders: rows.map(toOrderDTO) });
});

ordersRouter.get("/:id", async (req: AuthedRequest, res) => {
  const row = await prisma.order.findFirst({
    where: { id: (req.params.id as string), userId: req.userId },
    include: { cadFile: true },
  });
  if (!row) return res.status(404).json({ error: "Order not found" });
  res.json({ order: toOrderDTO(row) });
});

const orderInputSchema = z.object({
  partName: z.string().min(1).max(120),
  materialId: z.enum(Object.keys(MATERIALS) as [string, ...string[]]),
  partWeightG: z.number().positive().max(5000),
  wallThicknessMm: z.number().positive().max(20),
  quantity: z.number().int().positive().max(1_000_000),
  cavities: z.number().int().positive().max(64),
  tolerance: z.enum(["standard", "precision", "high-precision"]),
  finish: z.enum(["as-molded", "textured", "polished"]),
  color: z.enum(["natural", "black", "custom"]),
  newTool: z.boolean(),
  amortizeTooling: z.boolean(),
});

// multipart/form-data: field "input" is the JSON-encoded spec above,
// optional field "cadFile" is an .stl upload that gets parsed and persisted
// alongside the order it's attached to.
ordersRouter.post("/", upload.single("cadFile"), async (req: AuthedRequest, res) => {
  let rawInput: unknown;
  try {
    rawInput = JSON.parse(req.body.input ?? "{}");
  } catch {
    return res.status(400).json({ error: "Field 'input' must be valid JSON" });
  }
  const parsed = orderInputSchema.safeParse(rawInput);
  if (!parsed.success) {
    return res.status(400).json({ error: "Invalid order input", details: parsed.error.flatten() });
  }

  const result = computeQuote(parsed.data as any);

  const order = await prisma.order.create({
    data: {
      userId: req.userId!,
      partName: parsed.data.partName,
      materialId: parsed.data.materialId,
      partWeightG: parsed.data.partWeightG,
      wallThicknessMm: parsed.data.wallThicknessMm,
      quantity: parsed.data.quantity,
      cavities: parsed.data.cavities,
      tolerance: parsed.data.tolerance,
      finish: parsed.data.finish,
      color: parsed.data.color,
      newTool: parsed.data.newTool,
      amortizeTooling: parsed.data.amortizeTooling,
      unitPrice: result.unitPrice,
      partsSubtotal: result.partsSubtotal,
      toolingCost: result.toolingCost,
      toolingAmortized: result.toolingAmortized,
      grandTotal: result.grandTotal,
      currency: result.currency,
      estimatedCycleTimeSec: result.estimatedCycleTimeSec,
      estimatedLeadTimeDays: result.estimatedLeadTimeDays,
      breakdownJson: JSON.stringify(result.breakdown),
      status: "quote_requested",
      paymentStatus: "unpaid",
    },
  });

  if (req.file) {
    if (!req.file.originalname.toLowerCase().endsWith(".stl")) {
      return res.status(400).json({ error: "Only .stl CAD files are supported" });
    }
    try {
      const geometry = parseStl(req.file.buffer);
      await mkdir(UPLOAD_DIR, { recursive: true });
      const storedName = `${randomUUID()}.stl`;
      await writeFile(path.join(UPLOAD_DIR, storedName), req.file.buffer);
      await prisma.cadFile.create({
        data: {
          orderId: order.id,
          filename: req.file.originalname,
          storedPath: storedName,
          volumeCm3: geometry.volumeCm3,
          surfaceAreaCm2: geometry.surfaceAreaCm2,
          bboxXMm: geometry.bboxXMm,
          bboxYMm: geometry.bboxYMm,
          bboxZMm: geometry.bboxZMm,
          triangleCount: geometry.triangleCount,
        },
      });
    } catch (err) {
      // Order is already saved; a bad CAD file shouldn't roll that back —
      // surface the parse failure without the geometry attachment.
      console.error("CAD parse/store failed for order", order.id, err);
    }
  }

  const full = await prisma.order.findUniqueOrThrow({ where: { id: order.id }, include: { cadFile: true } });
  res.status(201).json({ order: toOrderDTO(full) });
});
