import { Router } from "express";
import { randomBytes } from "node:crypto";
import { prisma } from "../lib/prisma.js";
import { getStripe, isStripeConfigured } from "../lib/stripe.js";
import { requireAuth, type AuthedRequest } from "../middleware/requireAuth.js";

export const paymentsRouter = Router();

const FRONTEND_URL = process.env.FRONTEND_URL ?? "http://localhost:5173";

const RANDOM_LETTERS = "abcdefghijklmnopqrstuvwxyz";
function randomSuffix(length = 8): string {
  return Array.from(randomBytes(length))
    .map((b) => RANDOM_LETTERS[b % RANDOM_LETTERS.length])
    .join("");
}

paymentsRouter.post("/orders/:id/checkout", requireAuth, async (req: AuthedRequest, res) => {
  if (!isStripeConfigured()) {
    return res.status(501).json({
      error:
        "Stripe isn't configured yet. Set STRIPE_SECRET_KEY in backend/.env to enable payments.",
    });
  }
  const stripe = getStripe()!;

  const order = await prisma.order.findFirst({ where: { id: (req.params.id as string), userId: req.userId } });
  if (!order) return res.status(404).json({ error: "Order not found" });
  if (order.paymentStatus === "paid") {
    return res.status(400).json({ error: "This order is already paid" });
  }

  const session = await stripe.checkout.sessions.create({
    mode: "payment",
    line_items: [
      {
        price_data: {
          currency: order.currency.toLowerCase(),
          unit_amount: Math.round(order.grandTotal * 100),
          product_data: {
            name: order.partName,
            description: `${order.quantity.toLocaleString()} pcs · ${order.materialId.toUpperCase()} · order ${order.id}`,
          },
        },
        quantity: 1,
      },
    ],
    success_url: `${FRONTEND_URL}/portal/orders/${order.id}?payment=success`,
    cancel_url: `${FRONTEND_URL}/portal/orders/${order.id}?payment=cancelled`,
    metadata: { orderId: order.id },
    integration_identifier: `injectionmoldportal${randomSuffix()}`,
  });

  await prisma.order.update({ where: { id: order.id }, data: { stripeSessionId: session.id } });

  res.json({ checkoutUrl: session.url });
});

/**
 * Mounted with a raw-body parser in server.ts (Stripe signature verification
 * needs the exact request bytes, not JSON-parsed-and-re-serialized).
 */
export async function stripeWebhookHandler(req: import("express").Request, res: import("express").Response) {
  if (!isStripeConfigured()) {
    return res.status(501).json({ error: "Stripe isn't configured" });
  }
  const stripe = getStripe()!;
  const signature = req.headers["stripe-signature"];
  const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET;

  // Signature verification is mandatory — never process an unverified body,
  // even in local dev. `stripe listen` always hands you a webhook secret.
  if (!webhookSecret || !signature) {
    return res.status(400).json({
      error: "Webhook signing secret not configured. Set STRIPE_WEBHOOK_SECRET in backend/.env.",
    });
  }

  let event;
  try {
    event = stripe.webhooks.constructEvent(req.body, signature, webhookSecret);
  } catch (err) {
    return res.status(400).json({ error: `Webhook signature verification failed: ${err}` });
  }

  // Fulfillment lives here, not on the success page — a customer can pay and
  // never load the return URL. Both completed and async-succeeded need
  // handling, gated on payment_status so a still-pending async method isn't
  // fulfilled early.
  if (event.type === "checkout.session.completed" || event.type === "checkout.session.async_payment_succeeded") {
    const session = event.data.object as {
      metadata?: { orderId?: string };
      payment_intent?: string;
      payment_status?: string;
    };
    const orderId = session.metadata?.orderId;
    if (orderId && session.payment_status !== "unpaid") {
      await prisma.order.update({
        where: { id: orderId },
        data: {
          paymentStatus: "paid",
          stripePaymentIntentId:
            typeof session.payment_intent === "string" ? session.payment_intent : undefined,
        },
      });
    }
  }

  if (event.type === "checkout.session.async_payment_failed") {
    const session = event.data.object as { metadata?: { orderId?: string } };
    const orderId = session.metadata?.orderId;
    if (orderId) {
      await prisma.order.update({ where: { id: orderId }, data: { paymentStatus: "unpaid" } });
    }
  }

  res.json({ received: true });
}
