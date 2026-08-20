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
  /** THB per kg, virgin resin */
  pricePerKg: number;
  /** relative cooling-rate factor used in cycle-time estimate (higher = slower to cool) */
  coolingFactor: number;
  notes: string;
  notesTh: string;
}

export const MATERIALS: Record<MaterialId, Material> = {
  abs: {
    id: "abs",
    name: "ABS",
    density: 1.05,
    pricePerKg: 80,
    coolingFactor: 2.0,
    notes: "General purpose, good impact strength, easy to mold.",
    notesTh: "ใช้งานทั่วไป ทนแรงกระแทกดี ขึ้นรูปง่าย",
  },
  pp: {
    id: "pp",
    name: "Polypropylene (PP)",
    density: 0.9,
    pricePerKg: 49,
    coolingFactor: 1.6,
    notes: "Low cost, chemical resistant, living-hinge friendly.",
    notesTh: "ราคาประหยัด ทนสารเคมี เหมาะกับบานพับพลาสติก",
  },
  pom: {
    id: "pom",
    name: "Acetal / POM (Delrin)",
    density: 1.41,
    pricePerKg: 110,
    coolingFactor: 2.4,
    notes: "High stiffness and low friction, precision parts, gears.",
    notesTh: "แข็งแรง แรงเสียดทานต่ำ เหมาะกับชิ้นงานละเอียดและเฟือง",
  },
  pa6: {
    id: "pa6",
    name: "Nylon PA6",
    density: 1.14,
    pricePerKg: 100,
    coolingFactor: 2.0,
    notes: "Tough, wear resistant, absorbs moisture.",
    notesTh: "ทนทาน ทนการสึกหรอ ดูดความชื้นได้",
  },
  pc: {
    id: "pc",
    name: "Polycarbonate (PC)",
    density: 1.2,
    pricePerKg: 125,
    coolingFactor: 2.8,
    notes: "High impact and heat resistance, optically clear grades available.",
    notesTh: "ทนแรงกระแทกและความร้อนสูง มีเกรดใสให้เลือก",
  },
  "pc-abs": {
    id: "pc-abs",
    name: "PC/ABS Blend",
    density: 1.12,
    pricePerKg: 110,
    coolingFactor: 2.4,
    notes: "Balance of PC toughness and ABS moldability, common in enclosures.",
    notesTh: "สมดุลความทนทานของ PC กับความง่ายในการขึ้นรูปของ ABS นิยมใช้ทำเคส",
  },
  hdpe: {
    id: "hdpe",
    name: "HDPE",
    density: 0.955,
    pricePerKg: 45,
    coolingFactor: 1.7,
    notes: "Chemical resistant, common for containers and fluid parts.",
    notesTh: "ทนสารเคมี นิยมใช้ทำภาชนะและชิ้นงานสัมผัสของเหลว",
  },
  tpu: {
    id: "tpu",
    name: "TPU (Elastomer)",
    density: 1.21,
    pricePerKg: 170,
    coolingFactor: 2.6,
    notes: "Flexible, abrasion resistant, overmolding and soft-touch parts.",
    notesTh: "ยืดหยุ่น ทนการเสียดสี เหมาะกับงานโอเวอร์โมลด์และผิวสัมผัสนุ่ม",
  },
};

export const MATERIAL_LIST = Object.values(MATERIALS);
