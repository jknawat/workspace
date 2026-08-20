import { describe, expect, it } from "vitest";
import { parseStl } from "./stl-parser.js";

/** Builds a binary STL of an axis-aligned cube with the given edge length (mm). */
function buildCubeStl(size: number): Buffer {
  type V3 = [number, number, number];
  const tris: Array<[V3, V3, V3, V3]> = [
    [[0, 0, -1], [0, 0, 0], [size, 0, 0], [size, size, 0]],
    [[0, 0, -1], [0, 0, 0], [size, size, 0], [0, size, 0]],
    [[0, 0, 1], [0, 0, size], [size, size, size], [size, 0, size]],
    [[0, 0, 1], [0, 0, size], [0, size, size], [size, size, size]],
    [[0, -1, 0], [0, 0, 0], [size, 0, size], [size, 0, 0]],
    [[0, -1, 0], [0, 0, 0], [0, 0, size], [size, 0, size]],
    [[0, 1, 0], [0, size, 0], [size, size, 0], [size, size, size]],
    [[0, 1, 0], [0, size, 0], [size, size, size], [0, size, size]],
    [[-1, 0, 0], [0, 0, 0], [0, size, 0], [0, size, size]],
    [[-1, 0, 0], [0, 0, 0], [0, size, size], [0, 0, size]],
    [[1, 0, 0], [size, 0, 0], [size, size, size], [size, size, 0]],
    [[1, 0, 0], [size, 0, 0], [size, 0, size], [size, size, size]],
  ];

  const buf = Buffer.alloc(84 + tris.length * 50);
  buf.write("test cube".padEnd(80, " "), 0, "ascii");
  buf.writeUInt32LE(tris.length, 80);
  let offset = 84;
  for (const quad of tris) {
    for (const v of quad) {
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
  });
});

describe("parseStl — errors", () => {
  it("throws on a file with no triangles", () => {
    expect(() => parseStl(Buffer.from("solid empty\nendsolid empty", "utf-8"))).toThrow();
  });
});
