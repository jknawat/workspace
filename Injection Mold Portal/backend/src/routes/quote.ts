import { Router } from "express";
import { z } from "zod";
import { computeQuote } from "../lib/pricing.js";
import { MATERIALS } from "../data/materials.js";

export const quoteRouter = Router();

const quoteInputSchema = z.object({
  partName: z.string().max(120).default(""),
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

quoteRouter.post("/", (req, res) => {
  const parsed = quoteInputSchema.safeParse(req.body);
  if (!parsed.success) {
    return res.status(400).json({ error: "Invalid quote input", details: parsed.error.flatten() });
  }
  try {
    const result = computeQuote(parsed.data as any);
    res.json({ input: parsed.data, result });
  } catch (err) {
    res.status(400).json({ error: err instanceof Error ? err.message : "Failed to compute quote" });
  }
});
