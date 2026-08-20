export type MaterialId =
  | "abs"
  | "pp"
  | "pom"
  | "pa6"
  | "pc"
  | "pc-abs"
  | "hdpe"
  | "tpu";

export interface Material {
  id: MaterialId;
  name: string;
  /** g/cm3 */
  density: number;
  /** USD per kg, virgin resin */
  pricePerKg: number;
  /** relative cooling-rate factor used in cycle-time estimate (higher = slower to cool) */
  coolingFactor: number;
  notes: string;
}

export const MATERIALS: Record<MaterialId, Material> = {
  abs: {
    id: "abs",
    name: "ABS",
    density: 1.05,
    pricePerKg: 2.3,
    coolingFactor: 2.0,
    notes: "General purpose, good impact strength, easy to mold.",
  },
  pp: {
    id: "pp",
    name: "Polypropylene (PP)",
    density: 0.9,
    pricePerKg: 1.4,
    coolingFactor: 1.6,
    notes: "Low cost, chemical resistant, living-hinge friendly.",
  },
  pom: {
    id: "pom",
    name: "Acetal / POM (Delrin)",
    density: 1.41,
    pricePerKg: 3.1,
    coolingFactor: 2.4,
    notes: "High stiffness and low friction, precision parts, gears.",
  },
  pa6: {
    id: "pa6",
    name: "Nylon PA6",
    density: 1.14,
    pricePerKg: 2.9,
    coolingFactor: 2.0,
    notes: "Tough, wear resistant, absorbs moisture.",
  },
  pc: {
    id: "pc",
    name: "Polycarbonate (PC)",
    density: 1.2,
    pricePerKg: 3.6,
    coolingFactor: 2.8,
    notes: "High impact and heat resistance, optically clear grades available.",
  },
  "pc-abs": {
    id: "pc-abs",
    name: "PC/ABS Blend",
    density: 1.12,
    pricePerKg: 3.2,
    coolingFactor: 2.4,
    notes: "Balance of PC toughness and ABS moldability, common in enclosures.",
  },
  hdpe: {
    id: "hdpe",
    name: "HDPE",
    density: 0.955,
    pricePerKg: 1.3,
    coolingFactor: 1.7,
    notes: "Chemical resistant, common for containers and fluid parts.",
  },
  tpu: {
    id: "tpu",
    name: "TPU (Elastomer)",
    density: 1.21,
    pricePerKg: 4.8,
    coolingFactor: 2.6,
    notes: "Flexible, abrasion resistant, overmolding and soft-touch parts.",
  },
};

export const MATERIAL_LIST = Object.values(MATERIALS);
