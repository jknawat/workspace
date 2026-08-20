import { Router } from "express";
import multer from "multer";
import { parseStl } from "../lib/stl-parser.js";
import { MATERIALS, type MaterialId } from "../data/materials.js";

export const cadRouter = Router();

const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 25 * 1024 * 1024 }, // 25MB
});

/**
 * Stateless preview: parse an uploaded STL and return real geometry (volume,
 * surface area, bounding box) plus an estimated part weight for the given
 * material. Nothing is persisted here — persistence happens when the quote
 * is saved as an order (see routes/orders.ts).
 */
cadRouter.post("/parse", upload.single("file"), (req, res) => {
  if (!req.file) {
    return res.status(400).json({ error: "No file uploaded (expected multipart field 'file')" });
  }
  if (!req.file.originalname.toLowerCase().endsWith(".stl")) {
    return res.status(400).json({ error: "Only .stl files are supported" });
  }

  const materialId = (req.query.materialId as MaterialId) ?? "abs";
  const material = MATERIALS[materialId];
  if (!material) {
    return res.status(400).json({ error: `Unknown material: ${materialId}` });
  }

  try {
    const geometry = parseStl(req.file.buffer);
    const estimatedWeightG = geometry.volumeCm3 * material.density;
    res.json({
      filename: req.file.originalname,
      geometry,
      estimatedWeightG: Math.round(estimatedWeightG * 100) / 100,
      materialId,
    });
  } catch (err) {
    res.status(400).json({ error: err instanceof Error ? err.message : "Could not parse STL file" });
  }
});
