import { Router } from "express";
import { MATERIAL_LIST } from "../data/materials.js";

export const materialsRouter = Router();

materialsRouter.get("/", (_req, res) => {
  res.json({ materials: MATERIAL_LIST });
});
