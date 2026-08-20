import Stripe from "stripe";

let client: Stripe | null = null;
let attempted = false;

/** Returns null (never throws) when STRIPE_SECRET_KEY isn't configured yet. */
export function getStripe(): Stripe | null {
  if (!attempted) {
    attempted = true;
    const key = process.env.STRIPE_SECRET_KEY;
    if (key) {
      client = new Stripe(key);
    }
  }
  return client;
}

export function isStripeConfigured(): boolean {
  return Boolean(process.env.STRIPE_SECRET_KEY);
}
