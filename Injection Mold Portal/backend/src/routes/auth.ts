import { Router } from "express";
import bcrypt from "bcryptjs";
import { z } from "zod";
import { prisma } from "../lib/prisma.js";
import { signToken } from "../lib/auth.js";
import { requireAuth, type AuthedRequest } from "../middleware/requireAuth.js";

export const authRouter = Router();

const registerSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8).max(200),
  companyName: z.string().min(1).max(200),
});

authRouter.post("/register", async (req, res) => {
  const parsed = registerSchema.safeParse(req.body);
  if (!parsed.success) {
    return res.status(400).json({ error: "Invalid registration input", details: parsed.error.flatten() });
  }
  const { email, password, companyName } = parsed.data;

  const existing = await prisma.user.findUnique({ where: { email } });
  if (existing) {
    return res.status(409).json({ error: "An account with this email already exists" });
  }

  const user = await prisma.user.create({
    data: {
      email,
      passwordHash: bcrypt.hashSync(password, 8),
      companyName,
      role: "customer",
    },
  });
  const token = signToken({ sub: user.id, email: user.email, role: user.role });
  res.status(201).json({ token, user: publicUser(user) });
});

const loginSchema = z.object({
  email: z.string().email(),
  password: z.string().min(1),
});

authRouter.post("/login", async (req, res) => {
  const parsed = loginSchema.safeParse(req.body);
  if (!parsed.success) {
    return res.status(400).json({ error: "Invalid login input" });
  }
  const { email, password } = parsed.data;
  const user = await prisma.user.findUnique({ where: { email } });
  if (!user || !bcrypt.compareSync(password, user.passwordHash)) {
    return res.status(401).json({ error: "Invalid email or password" });
  }
  const token = signToken({ sub: user.id, email: user.email, role: user.role });
  res.json({ token, user: publicUser(user) });
});

authRouter.get("/me", requireAuth, async (req: AuthedRequest, res) => {
  const user = await prisma.user.findUnique({ where: { id: req.userId } });
  if (!user) return res.status(404).json({ error: "User not found" });
  res.json({ user: publicUser(user) });
});

function publicUser(u: { id: string; email: string; companyName: string; role: string; createdAt: Date }) {
  return { id: u.id, email: u.email, companyName: u.companyName, role: u.role, createdAt: u.createdAt };
}
