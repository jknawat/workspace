import { describe, expect, it } from "vitest";
import { parseStl } from "./stl-parser.js";

type V3 = [number, number, number];
type Tri = [V3, V3, V3];

/** Binary-STL-encodes a triangle soup. Normals are computed from winding order. */
function trianglesToStl(tris: Tri[]): Buffer {
  const buf = Buffer.alloc(84 + tris.length * 50);
  buf.write("test mesh".padEnd(80, " "), 0, "ascii");
  buf.writeUInt32LE(tris.length, 80);
  let offset = 84;
  for (const [a, b, c] of tris) {
    offset += 12; // normal — leave zeroed, parser recomputes geometry from vertices
    for (const v of [a, b, c]) {
      buf.writeFloatLE(v[0], offset);
      buf.writeFloatLE(v[1], offset + 4);
      buf.writeFloatLE(v[2], offset + 8);
      offset += 12;
    }
    buf.writeUInt16LE(0, offset);
    offset += 2;
  }
  return buf;
}

/**
 * Builds an axis-aligned cube (12 triangles, one quad per face). Winding is
 * verified to give outward-facing normals via cross(v2-v1, v3-v1) — the same
 * convention parseStl uses for its inward wall-thickness raycasts, so a
 * backward-wound test fixture would make every ray miss (as it did before
 * this comment existed).
 */
function buildCubeStl(size: number): Buffer {
  const s = size;
  const tris: Tri[] = [
    [[0, 0, 0], [0, s, 0], [s, 0, 0]],
    [[s, 0, 0], [0, s, 0], [s, s, 0]], // z=0, normal -z
    [[0, 0, s], [s, 0, s], [0, s, s]],
    [[s, 0, s], [s, s, s], [0, s, s]], // z=s, normal +z
    [[0, 0, 0], [s, 0, 0], [0, 0, s]],
    [[s, 0, 0], [s, 0, s], [0, 0, s]], // y=0, normal -y
    [[0, s, 0], [0, s, s], [s, s, 0]],
    [[s, s, 0], [0, s, s], [s, s, s]], // y=s, normal +y
    [[0, 0, 0], [0, 0, s], [0, s, 0]],
    [[0, s, 0], [0, 0, s], [0, s, s]], // x=0, normal -x
    [[s, 0, 0], [s, s, 0], [s, 0, s]],
    [[s, s, 0], [s, s, s], [s, 0, s]], // x=s, normal +x
  ];
  return trianglesToStl(tris);
}

/**
 * Builds a thin rectangular panel — top/bottom faces subdivided into a fine
 * grid (as a real CAD export would tessellate a large flat face), thin sides
 * left coarse. This is the shape that makes the wall-thickness estimator's
 * median-over-samples approach actually work: most triangles sit on the
 * thin-direction faces, same as a real molded shell. Winding follows the
 * same verified outward-normal pattern as buildCubeStl, generalized to
 * width/depth/thickness.
 */
function buildThinPanelStl(width: number, depth: number, thickness: number, grid: number): Buffer {
  const tris: Tri[] = [];
  const dx = width / grid;
  const dy = depth / grid;
  for (let i = 0; i < grid; i++) {
    for (let j = 0; j < grid; j++) {
      const x0 = i * dx, x1 = (i + 1) * dx;
      const y0 = j * dy, y1 = (j + 1) * dy;
      // bottom (z=0, normal -z)
      tris.push([[x0, y0, 0], [x0, y1, 0], [x1, y0, 0]]);
      tris.push([[x1, y0, 0], [x0, y1, 0], [x1, y1, 0]]);
      // top (z=thickness, normal +z)
      tris.push([[x0, y0, thickness], [x1, y0, thickness], [x0, y1, thickness]]);
      tris.push([[x1, y0, thickness], [x1, y1, thickness], [x0, y1, thickness]]);
    }
  }
  const w = width, d = depth, t = thickness;
  tris.push([[0, 0, 0], [w, 0, 0], [0, 0, t]], [[w, 0, 0], [w, 0, t], [0, 0, t]]); // y=0, normal -y
  tris.push([[0, d, 0], [0, d, t], [w, d, 0]], [[w, d, 0], [0, d, t], [w, d, t]]); // y=d, normal +y
  tris.push([[0, 0, 0], [0, 0, t], [0, d, 0]], [[0, d, 0], [0, 0, t], [0, d, t]]); // x=0, normal -x
  tris.push([[w, 0, 0], [w, d, 0], [w, 0, t]], [[w, d, 0], [w, d, t], [w, 0, t]]); // x=w, normal +x
  return trianglesToStl(tris);
}

describe("parseStl — binary", () => {
  it("computes exact volume, surface area, and bbox for a 20mm cube", () => {
    const geometry = parseStl(buildCubeStl(20));
    expect(geometry.triangleCount).toBe(12);
    expect(geometry.volumeCm3).toBeCloseTo(8, 6); // 20^3 mm^3 = 8000 mm^3 = 8 cm^3
    expect(geometry.surfaceAreaCm2).toBeCloseTo(24, 6); // 6 * 20^2 mm^2 = 2400 mm^2 = 24 cm^2
    expect(geometry.bboxXMm).toBeCloseTo(20, 6);
    expect(geometry.bboxYMm).toBeCloseTo(20, 6);
    expect(geometry.bboxZMm).toBeCloseTo(20, 6);
  });

  it("scales volume with the cube of edge length", () => {
    const small = parseStl(buildCubeStl(10));
    const large = parseStl(buildCubeStl(20));
    expect(large.volumeCm3).toBeCloseTo(small.volumeCm3 * 8, 5);
  });

  it("reads a solid cube's wall thickness as its own edge length", () => {
    // for a solid (not a shell), the nearest opposite surface IS the far
    // face — thickness collapses to the object's own extent in that axis
    const geometry = parseStl(buildCubeStl(20));
    expect(geometry.estimatedWallThicknessMm).not.toBeNull();
    expect(geometry.estimatedWallThicknessMm!).toBeCloseTo(20, 0);
  });
});

describe("parseStl — wall thickness on a thin panel", () => {
  it("reads back the true thickness of a finely-tessellated thin shell", () => {
    // 60x40mm panel, 2mm thick, with the large faces finely gridded like a
    // real CAD export — most triangles are on the thin-direction faces
    const geometry = parseStl(buildThinPanelStl(60, 40, 2, 12));
    expect(geometry.estimatedWallThicknessMm).not.toBeNull();
    expect(geometry.estimatedWallThicknessMm!).toBeCloseTo(2, 1);
  });

  it("scales the reading with panel thickness", () => {
    const thin = parseStl(buildThinPanelStl(60, 40, 1.5, 12));
    const thick = parseStl(buildThinPanelStl(60, 40, 4, 12));
    expect(thick.estimatedWallThicknessMm!).toBeGreaterThan(thin.estimatedWallThicknessMm!);
  });
});

describe("parseStl — ASCII", () => {
  it("parses a single-triangle ASCII STL", () => {
    const ascii = [
      "solid single",
      "  facet normal 0 0 1",
      "    outer loop",
      "      vertex 0 0 0",
      "      vertex 10 0 0",
      "      vertex 0 10 0",
      "    endloop",
      "  endfacet",
      "endsolid single",
    ].join("\n");
    const geometry = parseStl(Buffer.from(ascii, "utf-8"));
    expect(geometry.triangleCount).toBe(1);
    expect(geometry.bboxXMm).toBeCloseTo(10, 6);
    expect(geometry.bboxYMm).toBeCloseTo(10, 6);
    // a flat triangle in the z=0 plane has zero volume
    expect(geometry.volumeCm3).toBeCloseTo(0, 6);
    expect(geometry.surfaceAreaCm2).toBeGreaterThan(0);
    // a single triangle has nothing to ray-cast against
    expect(geometry.estimatedWallThicknessMm).toBeNull();
  });
});

describe("parseStl — errors", () => {
  it("throws on a file with no triangles", () => {
    expect(() => parseStl(Buffer.from("solid empty\nendsolid empty", "utf-8"))).toThrow();
  });
});
