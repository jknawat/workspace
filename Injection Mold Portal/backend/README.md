# Backend

Express + TypeScript API for the Injection Mold Portal.

## Run

```bash
npm install
npx prisma db push   # create the SQLite schema (first run only)
npm run db:seed      # demo customer + admin + sample orders
npm run dev           # tsx watch, http://localhost:4000
```

```bash
npm run build   # tsc -> dist/
npm start       # run the built dist/server.js
```

Copy `.env.example` to `.env` first. `STRIPE_SECRET_KEY`/`STRIPE_WEBHOOK_SECRET`
are optional — payment endpoints return a clear 501 until they're set. See
[`../docs/architecture.md#running-stripe-locally`](../docs/architecture.md#running-stripe-locally)
for getting real test-mode keys via the Stripe CLI (no account signup needed).

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/health` | — | Liveness check |
| GET | `/api/materials` | — | Available resins with density/price/cooling factor |
| POST | `/api/quote` | — | Compute a price for a part spec, no persistence |
| POST | `/api/cad/parse` | — | Parse an uploaded `.stl` (multipart `file`), return volume/surface-area/bbox + estimated weight for a material |
| POST | `/api/auth/register` | — | Create an account (`role: "customer"`) |
| POST | `/api/auth/login` | — | Log in |
| GET | `/api/auth/me` | Bearer | Current user |
| GET | `/api/orders` | Bearer | List the caller's orders |
| GET | `/api/orders/:id` | Bearer | One order |
| POST | `/api/orders` | Bearer | Multipart: `input` (JSON spec) + optional `cadFile` (`.stl`) — computes a quote, saves it as an order, persists the CAD geometry if a file was sent |
| POST | `/api/orders/:id/checkout` | Bearer | Create a Stripe Checkout Session for the order, returns `checkoutUrl` |
| POST | `/api/stripe/webhook` | Stripe signature | Fulfillment: marks an order `paid` on `checkout.session.completed`/`async_payment_succeeded` |
| GET | `/api/admin/stats` | Bearer + admin | Order count, customer count, revenue, pipeline value, active production |
| GET | `/api/admin/orders` | Bearer + admin | Every order, every customer |
| GET | `/api/admin/orders/:id` | Bearer + admin | One order + customer info |
| PATCH | `/api/admin/orders/:id/status` | Bearer + admin | Change an order's pipeline status |
| GET | `/api/admin/customers` | Bearer + admin | Customer list with order count / lifetime value |

## Data

SQLite via Prisma (`prisma/schema.prisma`), driver-adapter setup
(`@prisma/adapter-better-sqlite3` — Prisma 7 requires an adapter rather than a
bare connection string for SQL providers). `src/lib/prisma.ts` is the client
instance; `src/lib/dto.ts` reassembles the flat DB row into the nested
`{ input, result }` shape the API and frontend share. Uploaded STL files land
in `uploads/` (gitignored), referenced by the `CadFile` table.

Reset:

```bash
rm -f dev.db && npx prisma db push && npm run db:seed
```

## Pricing engine

`src/lib/pricing.ts` implements the cost model: material cost (weight × resin price
+ scrap allowance), cycle time (cooling-time rule of thumb driven by wall thickness
and a material-specific cooling factor, plus tolerance overhead), machine time cost
(cycle time × press rate ÷ cavity count), finish/color adders, and optional tooling
cost (amortized into the unit price or billed upfront). See
[`../docs/architecture.md`](../docs/architecture.md) for the reasoning behind it.

## CAD geometry

`src/lib/stl-parser.ts` parses binary or ASCII STL and computes real volume
(signed-tetrahedron sum), surface area, and bounding box — verified against a
known-answer 20mm test cube (8 cm³ / 24 cm² exactly). No CAD-kernel dependency;
STEP/IGES would need one (see architecture doc).
