# PriceTruth AI

React + TypeScript + Tailwind frontend, FastAPI backend, PostgreSQL storage, and a separate APScheduler worker. The app records page evidence and never treats a missing value as a zero price or a stock state.

## Run with Docker Compose

1. Copy `.env.example` to `.env` and choose a local database password.
2. Run `docker compose up --build`.
3. Open <http://localhost:8080>. API health: <http://localhost:8001/api/health>.

The first run applies the initial Alembic migration. PostgreSQL data persists in the `postgres_data` named volume. The worker runs every 30 seconds and processes due tracking jobs. Price alerts support `any_drop` and `target_price` modes, are scoped to exact verified listings, and persist their events for deduplication. Tracking is local-instance scoped; this build has no user accounts or external notification channel.

## Current retailer status

There are distinct URL adapters/domains for Amazon India, Flipkart, Shopsy, Myntra, Meesho, AJIO, and Croma. They conservatively extract Schema.org Product JSON-LD and Open Graph/title/image metadata. A fixture proves the parser code path; it does not prove live access or per-retailer extraction quality. The UI/API marks URL extraction as `configured_unverified`; a discovery run is created automatically and each platform is checked independently. No two additional platforms were approved, so the configured list remains these seven.

Automated search adapters generate identity queries and check the fully encoded retailer search URL against the current robots rules before fetching it. Live robots checks on 2026-10-27 showed that Flipkart and Shopsy disallow `/search?`, Meesho disallows `/search`, AJIO disallows `/search` and `/*/search/*`, and Croma disallows `/searchB` and search query parameters using `q`; those search pages are not fetched. Amazon India's robots endpoint returned 503 and Myntra's returned a maintenance page, so their search permissions remain unverified and fail closed. Search-access failures are reported as `could_not_check` when no other permitted source yields a candidate. Sitemaps remain the fallback and user-pasted product URLs remain available.

The discovery workflow attempts a retailer-specific search URL only after the current robots rules permit that exact query URL, and supplements search results with sitemap URLs declared in robots. It checks robots permission for every search, sitemap, and candidate page, caps sitemap size/count and candidate fetches, and never fetches a search route that robots disallows. The [published Flipkart robots file](https://www.flipkart.com/robots.txt) disallows `/search` paths; [Shopsy's robots file](https://www.shopsy.in/robots.txt) disallows `/search?`; [Meesho's robots file](https://www.meesho.com/robots.txt) disallows paths containing `/search`; [AJIO's robots file](https://www.ajio.com/robots.txt) disallows `/search` and `/*/search/*`. Amazon India's robots file returned an unavailable response and Myntra's returned a maintenance page during the access check; their rules therefore remain unverified. A sitemap declaration is only a discovery lead, not a blanket permission to crawl. Each operation fails closed when rules cannot be verified. See per-run results at `GET /api/discovery/{run_id}` and the platform baseline at `GET /api/platforms`.

If sitemap discovery cannot check a platform or finds no candidate, the UI offers the retailer homepage for manual search and accepts a user-provided product URL. That URL is still subject to HTTPS, retailer-domain, DNS, robots, parsing, matching, and timeout checks. Exact matches and probable/uncertain similar products are stored separately; similar products never enter the lowest-price calculation. The source retailer is shown as `source_checked` because submitting its own URL does not count as cross-listing discovery. Failed checks retry once and then remain `could_not_check`; a completed sitemap scan with no relevant candidate is `no_match_found`. Pages without extractable prices show `price_unavailable`. No state means an invented result. The app has not verified live integration quality for any retailer. Product pages requiring JavaScript may not yield data; Playwright is intentionally not enabled without a permitted-access finding for the target page.

## API

- `POST /api/products/inspect` with `{ "url": "https://..." }`
- `GET /api/products/{id}` and `/history`
- `GET /api/platforms`
- `GET /api/discovery/{run_id}` for persisted per-retailer status/candidates
- `POST /api/discovery/{run_id}/candidates` with `{ "url": "https://retailer-product-page" }` for a user-provided fallback
- `POST /api/tracking`, `GET /api/tracking`, `PATCH /api/tracking/{id}`, `GET /api/tracking/{id}/status`
- `GET /api/alerts`

All user-supplied URLs are restricted to HTTPS and the seven retailer domains; redirects are not followed. The backend rejects non-public DNS results. Network integrations should additionally pin resolved addresses against rebinding before broader exposure. Do not expose this local development deployment to untrusted users without adding authentication, deployment hardening, and a reviewed SSRF-safe transport.

## Tests and limits

Backend fixtures cover URL routing, Shopsy/Flipkart separation, structured parsing, missing prices, matching conflicts, and URL validation. No routine test contacts retailer pages. No live retailer integration has been verified. Product discovery, location-specific stock, deal verdicts, and outbound email/push are not implemented.
