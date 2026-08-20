# Injection Mold Portal

Instant plastic injection molding quotes and a customer portal to track orders
through tooling, production, QC and shipping — built in the spirit of
[wayn-industry.com](https://wayn-industry.com)'s instant-CNC-quoting portal, adapted
for plastic injection molding. See [`docs/architecture.md`](docs/architecture.md) for
the full reference-site analysis and how this project maps to it.

## Structure

- `backend/` — Express + TypeScript API: injection-molding cost engine, STL geometry
  parsing, auth (customer/admin roles), orders, Stripe payments — SQLite via Prisma
- `frontend/` — React + Vite + TypeScript + Tailwind app: marketing site, quote tool
  (with CAD upload), customer portal, admin console
- `docs/` — architecture notes

## Getting started

```bash
cd backend
npm install
npx prisma db push   # create the SQLite schema
npm run db:seed      # demo customer + admin + sample orders
npm run dev           # http://localhost:4000
```

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173, proxies /api to :4000
```

For payments to actually mark an order paid (not just create the Stripe
Checkout session), also run the Stripe CLI's webhook forwarder — see
[`docs/architecture.md#running-stripe-locally`](docs/architecture.md#running-stripe-locally).

Demo logins:

```
customer: demo@injectionmoldportal.com / demo1234
admin:    admin@injectionmoldportal.com / admin1234
```

## Status

Functional end to end, verified with a headless-browser pass through every flow:
instant quote calculator with a real cost-estimation engine, STL upload that
auto-fills part weight from actual parsed geometry, JWT auth with customer/admin
roles, a customer portal (dashboard, orders, order detail, account, Stripe
checkout), and an admin console (dashboard, all orders, status changes,
customers) — backed by a real SQLite database via Prisma.

Not done: real STEP/IGES CAD parsing (STL was chosen instead — see
[`docs/architecture.md`](docs/architecture.md) for the tradeoff), and this hasn't
been deployed anywhere — it's local-dev only so far.
