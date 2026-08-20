import express from "express";
import cors from "cors";
import "dotenv/config";
import { materialsRouter } from "./routes/materials.js";
import { quoteRouter } from "./routes/quote.js";
import { authRouter } from "./routes/auth.js";
import { ordersRouter } from "./routes/orders.js";
import { adminRouter } from "./routes/admin.js";
import { cadRouter } from "./routes/cad.js";
import { paymentsRouter, stripeWebhookHandler } from "./routes/payments.js";

const app = express();
app.use(cors());

// Stripe needs the raw request body to verify the webhook signature, so this
// is mounted before the global express.json() body parser.
app.post("/api/stripe/webhook", express.raw({ type: "application/json" }), stripeWebhookHandler);

app.use(express.json());

app.get("/api/health", (_req, res) => res.json({ ok: true, service: "injection-mold-portal-backend" }));

app.use("/api/materials", materialsRouter);
app.use("/api/quote", quoteRouter);
app.use("/api/auth", authRouter);
app.use("/api/orders", ordersRouter);
app.use("/api/admin", adminRouter);
app.use("/api/cad", cadRouter);
app.use("/api", paymentsRouter);

app.use((_req, res) => res.status(404).json({ error: "Not found" }));

const PORT = Number(process.env.PORT ?? 4000);
app.listen(PORT, () => {
  console.log(`injection-mold-portal-backend listening on http://localhost:${PORT}`);
});
