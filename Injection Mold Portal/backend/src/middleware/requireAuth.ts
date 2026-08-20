import type { NextFunction, Request, Response } from "express";
import { verifyToken } from "../lib/auth.js";

export interface AuthedRequest extends Request {
  userId?: string;
  userEmail?: string;
  userRole?: string;
}

export function requireAuth(req: AuthedRequest, res: Response, next: NextFunction) {
  const header = req.headers.authorization;
  if (!header?.startsWith("Bearer ")) {
    return res.status(401).json({ error: "Missing bearer token" });
  }
  try {
    const payload = verifyToken(header.slice("Bearer ".length));
    req.userId = payload.sub;
    req.userEmail = payload.email;
    req.userRole = payload.role;
    next();
  } catch {
    return res.status(401).json({ error: "Invalid or expired token" });
  }
}

export function requireAdmin(req: AuthedRequest, res: Response, next: NextFunction) {
  if (req.userRole !== "admin") {
    return res.status(403).json({ error: "Admin access required" });
  }
  next();
}
