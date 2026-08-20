export interface StlGeometry {
  triangleCount: number;
  /** signed-tetrahedron volume, mm^3 → converted to cm^3 */
  volumeCm3: number;
  surfaceAreaCm2: number;
  bboxXMm: number;
  bboxYMm: number;
  bboxZMm: number;
}

interface Vec3 {
  x: number;
  y: number;
  z: number;
}

/**
 * Parses an STL file (binary or ASCII) and computes real geometry —
 * volume via the signed-tetrahedron/divergence-theorem sum, surface area as
 * the sum of triangle areas, and an axis-aligned bounding box. Assumes the
 * file's units are millimeters, the STL convention for CAD/3D-printing tools.
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
  };
}

function isBinaryStl(buffer: Buffer): boolean {
  if (buffer.length < 84) return false;
  const triCount = buffer.readUInt32LE(80);
  const expectedSize = 84 + triCount * 50;
  return expectedSize === buffer.length;
}

function parseBinaryStl(buffer: Buffer): Array<[Vec3, Vec3, Vec3]> {
  const triCount = buffer.readUInt32LE(80);
  const triangles: Array<[Vec3, Vec3, Vec3]> = [];
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

function parseAsciiStl(buffer: Buffer): Array<[Vec3, Vec3, Vec3]> {
  const text = buffer.toString("utf-8");
  const vertexRe = /vertex\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)/g;
  const vertices: Vec3[] = [];
  let match: RegExpExecArray | null;
  while ((match = vertexRe.exec(text)) !== null) {
    vertices.push({ x: Number(match[1]), y: Number(match[2]), z: Number(match[3]) });
  }
  const triangles: Array<[Vec3, Vec3, Vec3]> = [];
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
  const ux = v2.x - v1.x;
  const uy = v2.y - v1.y;
  const uz = v2.z - v1.z;
  const vx = v3.x - v1.x;
  const vy = v3.y - v1.y;
  const vz = v3.z - v1.z;
  const cx = uy * vz - uz * vy;
  const cy = uz * vx - ux * vz;
  const cz = ux * vy - uy * vx;
  return Math.sqrt(cx * cx + cy * cy + cz * cz) / 2;
}
