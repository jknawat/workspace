export interface StlGeometry {
  triangleCount: number;
  /** signed-tetrahedron volume, mm^3 → converted to cm^3 */
  volumeCm3: number;
  surfaceAreaCm2: number;
  bboxXMm: number;
  bboxYMm: number;
  bboxZMm: number;
  /**
   * Estimated nominal wall thickness in mm, from ray-casting each sampled
   * face inward and measuring distance to the opposite surface (median of
   * all samples that hit). Null if the mesh is too degenerate/open to get a
   * reliable read — caller should fall back to manual entry.
   */
  estimatedWallThicknessMm: number | null;
}

interface Vec3 {
  x: number;
  y: number;
  z: number;
}

type Triangle = [Vec3, Vec3, Vec3];

const THICKNESS_SAMPLE_TRIANGLES = 200;
const THICKNESS_TARGET_TRIANGLES = 4000; // cap on the mesh tested against, for runtime
const RAY_EPSILON = 1e-4;

/**
 * Parses an STL file (binary or ASCII) and computes real geometry —
 * volume via the signed-tetrahedron/divergence-theorem sum, surface area as
 * the sum of triangle areas, an axis-aligned bounding box, and an estimated
 * wall thickness via inward ray-casting. Assumes the file's units are
 * millimeters, the STL convention for CAD/3D-printing tools.
 */
export function parseStl(buffer: Buffer): StlGeometry {
  const triangles = isBinaryStl(buffer) ? parseBinaryStl(buffer) : parseAsciiStl(buffer);
  if (triangles.length === 0) {
    throw new Error("No triangles found in STL file");
  }

  let signedVolumeSum = 0;
  let areaSum = 0;
  const min: Vec3 = { x: Infinity, y: Infinity, z: Infinity };
  const max: Vec3 = { x: -Infinity, y: -Infinity, z: -Infinity };

  for (const [v1, v2, v3] of triangles) {
    signedVolumeSum += signedTetrahedronVolume(v1, v2, v3);
    areaSum += triangleArea(v1, v2, v3);
    for (const v of [v1, v2, v3]) {
      min.x = Math.min(min.x, v.x);
      min.y = Math.min(min.y, v.y);
      min.z = Math.min(min.z, v.z);
      max.x = Math.max(max.x, v.x);
      max.y = Math.max(max.y, v.y);
      max.z = Math.max(max.z, v.z);
    }
  }

  return {
    triangleCount: triangles.length,
    volumeCm3: Math.abs(signedVolumeSum) / 1000,
    surfaceAreaCm2: areaSum / 100,
    bboxXMm: max.x - min.x,
    bboxYMm: max.y - min.y,
    bboxZMm: max.z - min.z,
    estimatedWallThicknessMm: estimateWallThickness(triangles),
  };
}

/**
 * Samples up to THICKNESS_SAMPLE_TRIANGLES faces, casts a ray from each
 * face's centroid inward along its (inward-facing) normal, and measures the
 * distance to the nearest opposite surface it hits — that's a local wall
 * thickness reading. Returns the median of all valid readings. This is the
 * same basic technique real DFM thickness-analysis tools use, simplified.
 */
function estimateWallThickness(triangles: Triangle[]): number | null {
  const targets = subsample(triangles, THICKNESS_TARGET_TRIANGLES);
  const samples = subsample(triangles, THICKNESS_SAMPLE_TRIANGLES);

  const readings: number[] = [];
  for (const tri of samples) {
    const centroid = triangleCentroid(tri);
    const normal = triangleNormal(tri);
    if (!normal) continue;
    // STL winding order gives an outward normal by convention; cast inward.
    const origin = offset(centroid, normal, -RAY_EPSILON);
    const direction = negate(normal);
    const hit = nearestRayHit(origin, direction, targets, tri);
    if (hit !== null && hit > RAY_EPSILON) {
      readings.push(hit);
    }
  }

  if (readings.length < 3) return null;
  readings.sort((a, b) => a - b);
  const mid = Math.floor(readings.length / 2);
  const median = readings.length % 2 === 0 ? (readings[mid - 1] + readings[mid]) / 2 : readings[mid];
  return Math.round(median * 100) / 100;
}

function subsample<T>(items: T[], max: number): T[] {
  if (items.length <= max) return items;
  const step = items.length / max;
  const out: T[] = [];
  for (let i = 0; i < max; i++) out.push(items[Math.floor(i * step)]);
  return out;
}

function nearestRayHit(origin: Vec3, direction: Vec3, targets: Triangle[], skip: Triangle): number | null {
  let nearest: number | null = null;
  for (const tri of targets) {
    if (tri === skip) continue;
    const t = rayTriangleIntersect(origin, direction, tri);
    if (t !== null && (nearest === null || t < nearest)) {
      nearest = t;
    }
  }
  return nearest;
}

/** Möller–Trumbore ray-triangle intersection. Returns distance along the ray, or null. */
function rayTriangleIntersect(origin: Vec3, dir: Vec3, [v0, v1, v2]: Triangle): number | null {
  const e1 = subtract(v1, v0);
  const e2 = subtract(v2, v0);
  const pvec = cross(dir, e2);
  const det = dot(e1, pvec);
  if (Math.abs(det) < 1e-9) return null; // parallel

  const invDet = 1 / det;
  const tvec = subtract(origin, v0);
  const u = dot(tvec, pvec) * invDet;
  if (u < 0 || u > 1) return null;

  const qvec = cross(tvec, e1);
  const v = dot(dir, qvec) * invDet;
  if (v < 0 || u + v > 1) return null;

  const t = dot(e2, qvec) * invDet;
  return t > 1e-9 ? t : null;
}

function isBinaryStl(buffer: Buffer): boolean {
  if (buffer.length < 84) return false;
  const triCount = buffer.readUInt32LE(80);
  const expectedSize = 84 + triCount * 50;
  return expectedSize === buffer.length;
}

function parseBinaryStl(buffer: Buffer): Triangle[] {
  const triCount = buffer.readUInt32LE(80);
  const triangles: Triangle[] = [];
  let offset = 84;
  for (let i = 0; i < triCount; i++) {
    offset += 12; // skip normal
    const v1 = readVec3(buffer, offset);
    offset += 12;
    const v2 = readVec3(buffer, offset);
    offset += 12;
    const v3 = readVec3(buffer, offset);
    offset += 12;
    offset += 2; // attribute byte count
    triangles.push([v1, v2, v3]);
  }
  return triangles;
}

function readVec3(buffer: Buffer, offset: number): Vec3 {
  return {
    x: buffer.readFloatLE(offset),
    y: buffer.readFloatLE(offset + 4),
    z: buffer.readFloatLE(offset + 8),
  };
}

function parseAsciiStl(buffer: Buffer): Triangle[] {
  const text = buffer.toString("utf-8");
  const vertexRe = /vertex\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)/g;
  const vertices: Vec3[] = [];
  let match: RegExpExecArray | null;
  while ((match = vertexRe.exec(text)) !== null) {
    vertices.push({ x: Number(match[1]), y: Number(match[2]), z: Number(match[3]) });
  }
  const triangles: Triangle[] = [];
  for (let i = 0; i + 2 < vertices.length; i += 3) {
    triangles.push([vertices[i], vertices[i + 1], vertices[i + 2]]);
  }
  return triangles;
}

function signedTetrahedronVolume(v1: Vec3, v2: Vec3, v3: Vec3): number {
  return (
    (v1.x * (v2.y * v3.z - v3.y * v2.z) -
      v1.y * (v2.x * v3.z - v3.x * v2.z) +
      v1.z * (v2.x * v3.y - v3.x * v2.y)) /
    6
  );
}

function triangleArea(v1: Vec3, v2: Vec3, v3: Vec3): number {
  const c = cross(subtract(v2, v1), subtract(v3, v1));
  return length(c) / 2;
}

function triangleCentroid([v1, v2, v3]: Triangle): Vec3 {
  return { x: (v1.x + v2.x + v3.x) / 3, y: (v1.y + v2.y + v3.y) / 3, z: (v1.z + v2.z + v3.z) / 3 };
}

function triangleNormal([v1, v2, v3]: Triangle): Vec3 | null {
  const n = cross(subtract(v2, v1), subtract(v3, v1));
  const len = length(n);
  if (len < 1e-12) return null;
  return { x: n.x / len, y: n.y / len, z: n.z / len };
}

function subtract(a: Vec3, b: Vec3): Vec3 {
  return { x: a.x - b.x, y: a.y - b.y, z: a.z - b.z };
}

function cross(a: Vec3, b: Vec3): Vec3 {
  return { x: a.y * b.z - a.z * b.y, y: a.z * b.x - a.x * b.z, z: a.x * b.y - a.y * b.x };
}

function dot(a: Vec3, b: Vec3): number {
  return a.x * b.x + a.y * b.y + a.z * b.z;
}

function length(a: Vec3): number {
  return Math.sqrt(dot(a, a));
}

function negate(a: Vec3): Vec3 {
  return { x: -a.x, y: -a.y, z: -a.z };
}

function offset(p: Vec3, dir: Vec3, dist: number): Vec3 {
  return { x: p.x + dir.x * dist, y: p.y + dir.y * dist, z: p.z + dir.z * dist };
}
