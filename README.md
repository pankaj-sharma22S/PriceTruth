# PriceTruth AI

PriceTruth AI is a product price comparison and tracking platform designed for Indian e-commerce. It helps users find the exact same product and variant across multiple online shopping platforms and compare verified, current selling prices in one transparent place without using paid retailer APIs.

## Architecture & Technology Stack

- **Frontend**: React + TypeScript + Tailwind CSS (Vite build, mobile-responsive, dark/accent-themed graphical UI).
- **Backend**: Python 3.11 + FastAPI (REST endpoints, SSRF protection, Pydantic validation, SQL persistence).
- **Database**: PostgreSQL 16 (in Docker with named volume `postgres_data` for persistent history and alerts) and SQLite fallback for local test suites.
- **Worker/Scheduler**: APScheduler running as an isolated worker service to handle candidate discovery, recurring price/stock checks, and alert evaluations.
- **Data Acquisition**: Retailer-specific adapters with structured Schema.org JSON-LD extraction, robust HTML CSS price selectors, and SSRF-safe bounded transports.
- **Variant Matching Engine**: Strict multi-attribute entity resolution (brand, model family, storage capacity, colour, variant modifiers such as Pro/Max/Plus/e, accessories separation, and conflicting attribute rejection).

## Supported Platforms (Seven Retailers)

1. **Amazon India** (`amazon.in`)
2. **Flipkart** (`flipkart.com`)
3. **Shopsy** (`shopsy.in`)
4. **Myntra** (`myntra.com`)
5. **Meesho** (`meesho.com`)
6. **AJIO** (`ajio.com`)
7. **Croma** (`croma.com`)

## Key Features & Capabilities

- **Product Link Input**: Submit an HTTPS product URL from any supported retailer.
- **Automated Product Identification**: Safely extracts title, manufacturer brand, model, storage, colour, and specs.
- **Cross-Platform Candidate Discovery**: Searches across the other six retailers for candidate listings matching the exact product identity.
- **Exact vs. Similar Product Separation**: Distinguishes the exact product variant (e.g., iPhone 15 Blue 128 GB) from different storage sizes, colours, or model generations (iPhone 15 Plus, iPhone 17e), keeping similar items out of lowest-price calculations.
- **Verified Selling Price Comparison**: Never invents prices or mixes up MRP list prices with actual selling prices.
- **Price History & Graphical Progression**: Tracks verified price observations over time with visual SVG progression charts.
- **Price Alerts & Stock Tracking**: Supports `any_drop` and `target_price` modes with deduplicated event recording.
- **User-Provided Candidate Fallback**: Allows pasting direct product links for platforms protected by bot challenges or restricted search routes.

## How to Run

### Option 1: Docker Compose (Full Stack)

```bash
# 1. Prepare environment
copy .env.example .env

# 2. Start database, backend, worker, and frontend
docker compose up --build

# 3. Access the web application
# Frontend: http://localhost:8080
# Backend API: http://localhost:8001/api/health
```

### Option 2: Local Development

```bash
# Backend & Tests:
cd backend
$env:PYTHONPATH="."
pytest -v

# Frontend:
cd frontend
npm install
npm run build
npm run dev
```

## Running the Automated Test Suite

The test suite contains 66 comprehensive automated unit and integration tests covering:
- Platform URL routing and separation (including Shopsy vs. Flipkart isolation)
- Structured Schema.org and HTML price selector extraction across platforms
- Cross-platform candidate discovery and sitemap fallback mechanisms
- Variant matching accuracy (exact matches, variant conflicts, accessory rejections)
- Database persistence, price observations, history, and alert rule evaluations
- SSRF prevention, IP validation, and URL safety

To run tests:
```bash
$env:PYTHONPATH="E:\last\backend"
cd E:\last\backend
pytest -v
```
All 66 tests pass cleanly.
