# Architecture

## Reference: wayn-industry.com/portal

`wayn-industry.com` is an instant-quoting portal for custom CNC machining. `/portal`
itself is authenticated (blocked in `robots.txt`), so its structure was reconstructed
from the public shell, `sitemap.xml`, and the compiled JS bundle rather than observed
directly:

- **Frontend:** React SPA, Vite-bundled, Framer Motion for animation. Static HTML head
  carries full JSON-LD (Organization, WebSite, Service, FAQPage) so the SPA is still
  crawlable.
- **Backend:** Decoupled API on Cloudflare Workers, called via `/api/...`.
- **Payments:** Stripe.
- **Public site map:** `/` (marketing), `/quote` (upload CAD → instant price),
  `/tools/`, `/resource/tool-hub/feed-and-speed`, `/resource/tolerance/`,
  `/resources`, `/terms`, `/privacy`.
- **Gated areas:** `/portal` (customer dashboard: orders, RFQs, files, invoices,
  account) and `/admin` (internal ops — the largest module in the bundle).
- **Core mechanic:** upload a CAD file, get an automated price with no manual
  quoting step.

## This project: Injection Mold Portal

Same core mechanic, applied to plastic injection molding — public site, customer
portal, admin console, real CAD geometry parsing, persistent database, and Stripe
payments:

- **Frontend** (`frontend/`) — React 19 + Vite + TypeScript + Tailwind v4. React
  Router for client-side routing. Dark, industrial theme in the spirit of the
  reference site; the admin console reuses the same component system with an
  orange accent instead of blue.
- **Backend** (`backend/`) — Node + Express + TypeScript, SQLite via Prisma
  (driver-adapter setup — Prisma 7 requires `@prisma/adapter-better-sqlite3`
  rather than a bare connection string). JWT auth (role embedded in the token:
  `customer` | `admin`), bcrypt password hashing, Zod request validation, multer
  for file uploads.
- **Quote engine** (`backend/src/lib/pricing.ts`) — the user fills a spec form
  (material, part weight, wall thickness, quantity, cavities, tolerance, finish,
  color, tooling), optionally auto-filled from a parsed CAD file. Price is
  computed from real injection-molding cost structure: material cost (weight ×
  resin price + scrap allowance), cycle time (cooling-time rule of thumb from
  wall thickness, material-specific cooling factor, tolerance overhead), machine
  time cost (cycle time × press rate ÷ cavity count), and optional tooling cost
  (amortized into the unit price or billed upfront).
- **CAD parsing** (`backend/src/lib/stl-parser.ts`) — real geometry from
  uploaded STL files (binary and ASCII), not a mock: volume via the
  signed-tetrahedron/divergence-theorem sum over the mesh, surface area as the
  sum of triangle areas, and an axis-aligned bounding box. Volume × material
  density auto-fills the part-weight field on the quote form. STEP/IGES (true
  B-rep CAD, what the reference site accepts) would need a geometry kernel
  (e.g. `opencascade.js`, a ~30MB WASM build) — STL was chosen instead for a much
  lighter dependency footprint while still computing real, non-mocked numbers.
  Wall thickness isn't derivable from a triangle mesh without shell/thickness
  analysis, so it stays a manual field.
- **Payments** — Stripe Checkout Sessions (hosted redirect, not the deprecated
  Charges API or a custom Elements form), following Stripe's own best-practice
  guidance: no `payment_method_types` override (dynamic payment methods),
  fulfillment driven from a signature-verified webhook handler (`checkout.session.completed`
  and `checkout.session.async_payment_succeeded`, gated on `payment_status`) rather
  than the success-page redirect, since a customer can pay and never load that
  page. Wired against a real Stripe test-mode sandbox (via `stripe sandbox
  create` — no account signup needed) rather than left as placeholder keys.
- **Admin console** — same auth system, gated by `role: "admin"` on the JWT and
  enforced server-side (`requireAdmin` middleware) as well as client-side
  routing. Ops can see every order across all customers, change an order's
  pipeline status, and view a customer list with lifetime value.

### Site map

| Route | Auth | Purpose |
|---|---|---|
| `/` | public | Marketing home |
| `/quote` | public | Instant quote calculator, optional STL upload |
| `/resources` | public | Material wall-thickness/draft/shrinkage guide + DFM checklist |
| `/terms`, `/privacy` | public | Legal placeholders |
| `/portal/login`, `/portal/register` | public | Auth (redirects by role after login) |
| `/portal` | customer | Dashboard: stat tiles, order-status chart, recent orders |
| `/portal/orders` | customer | Full order list |
| `/portal/orders/:id` | customer | Order detail: pipeline status, spec, CAD geometry, cost breakdown, Pay now |
| `/portal/account` | customer | Account info |
| `/admin` | admin | Ops dashboard: stats across all customers, status chart, recent orders |
| `/admin/orders` | admin | Every order, every customer |
| `/admin/orders/:id` | admin | Order detail + status-change control |
| `/admin/customers` | admin | Customer list with order count / lifetime value |

### Demo logins

```
customer: demo@injectionmoldportal.com / demo1234
admin:    admin@injectionmoldportal.com / admin1234
```

### Backend API

See [`../backend/README.md`](../backend/README.md) for the full endpoint table.

### Running Stripe locally

Checkout session creation works as soon as `STRIPE_SECRET_KEY` is set, but
**webhook-driven fulfillment needs the Stripe CLI forwarding events**:

```bash
stripe listen --forward-to localhost:4000/api/stripe/webhook
```

Copy the `whsec_...` it prints into `STRIPE_WEBHOOK_SECRET` in `backend/.env` and
restart the backend. Without this running, checkout sessions still get created
and the hosted Stripe page still works, but the order never flips to `paid`
locally (there's no public URL for Stripe's real webhook infrastructure to
reach). `backend/.env` already has a real sandbox test key wired in — the
sandbox was provisioned with `stripe sandbox create` (test mode, no Stripe
account signup needed) and is claimable at the URL that command prints, if you
want it to outlive its default 7-day expiry.

### Data

SQLite at `backend/dev.db` (gitignored — this is dev/demo data, not something to
commit). Reset and reseed:

```bash
cd backend
rm -f dev.db
npx prisma db push
npm run db:seed
```

Uploaded STL files persist to `backend/uploads/` (also gitignored), referenced
by path from the `CadFile` table.
