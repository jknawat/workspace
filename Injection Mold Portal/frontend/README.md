# Frontend

React + Vite + TypeScript + Tailwind v4 app for the Injection Mold Portal.

## Run

```bash
npm install
npm run dev     # http://localhost:5173, proxies /api to http://localhost:4000
npm run build
```

Requires the backend running on port 4000 (see `../backend`).

## Structure

- `src/pages/` — route-level pages (`Home`, `Quote`, `Resources`, `Terms`,
  `Privacy`), `src/pages/portal/` (`Login`, `Register`, `Dashboard`, `Orders`,
  `OrderDetail`, `Account`), `src/pages/admin/` (`Dashboard`, `Orders`,
  `OrderDetail`, `Customers`)
- `src/components/layout/` — `PublicLayout` (marketing nav/footer),
  `PortalLayout` (auth-gated sidebar shell), `AdminLayout` (role-gated, `role
  !== "admin"` bounces to `/portal`)
- `src/components/ui/` — `Button`, `Card`, `Badge`, `StatTile`
- `src/components/charts/` — hand-rolled SVG `OrdersStatusChart` (shared by
  both the customer and admin dashboards)
- `src/lib/` — `api.ts` (fetch client, including multipart uploads and
  `admin.*`), `auth-context.tsx` (JWT session, role-aware), `types.ts`

## Notable flows

- **Quote page CAD upload:** selecting an `.stl` calls `POST /api/cad/parse`
  and auto-fills part weight from the returned volume × material density.
  Re-picking the material recomputes the weight from the already-parsed
  geometry without re-uploading.
- **Checkout:** `OrderDetail`'s "Pay now" calls `POST /api/orders/:id/checkout`
  and does a full-page redirect to the returned Stripe-hosted URL. Payment
  status updates via webhook, not the return-page redirect — the page does one
  retry-fetch shortly after landing back on `?payment=success` in case the
  webhook is still in flight.
- **Auth redirect:** login sends customers to `/portal` and admins to
  `/admin`, unless a specific `from` location was set (only `Quote.tsx` does
  this deliberately, for "log in to save this quote"). The layout guards
  (`PortalLayout`/`AdminLayout`) intentionally don't set `from` on their own
  `!user` redirect — see the comment in `PortalLayout.tsx` for why (it raced
  against logout and could send the next login back to the previous user's page).

## Design tokens

Dark, industrial theme defined as CSS custom properties in `src/index.css`
(`@theme` block) — surfaces, ink, brand colors, and a fixed status palette
(good/warning/serious/critical) that's never reused for anything else. The
admin console reuses every token except swaps `brand-orange` in for
`brand-blue` on its wordmark, as a visual "you're in ops, not the storefront"
cue.
