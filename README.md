# Fromuth Scraper

Production-oriented supplier sync for Fromuth -> Shopify.

## What it does
- Crawls Fromuth category/filter pages and follows pagination.
- Discovers product URLs from listing cards.
- Parses product pages for title, brand, price, images, description, specifications, and inventory rows.
- Normalizes variants to Shopify options:
  - Option 1: Color
  - Option 2: Size
- Matches Shopify variants by exact SKU.
- Updates price + inventory for known variants.
- Adds missing variants to existing products.
- Creates brand-new draft products when a scraped product is not in Shopify yet.
- Safely zeros missing Shopify variants only when the product scrape is clearly valid.
- Writes:
  - `data/products.json`
  - `data/sync_results.json`

## Verified assumptions from the sample Fromuth pages
- Listing pages expose title, base SKU, price, and product links server-side.
- Product pages expose visible price and tab headings including Specifications and Inventory.
- Inventory lives on the product page and should be treated as the source of truth for Shopify variants.

## Important notes
- Fromuth appears to hide unavailable sizes instead of showing them as stock 0.
- Because of that, missing Shopify variants are only zeroed when the inventory table was found and at least one valid row was parsed.
- Backorder wording has not been fully validated yet. The code includes a conservative placeholder hook and logs unclear cases rather than forcing risky updates.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m src.main
```

## GitHub Actions
The workflow file is included at `.github/workflows/fromuth-sync.yml`.

## Selector hardening
The parser is deliberately heuristic because the exact tab and table markup may vary by template. If Fromuth changes the site, update:
- `src/scraper/product_parser.py`
- `src/scraper/discover.py`

## Shopify notes
This project uses the Shopify Admin REST API for portability and simplicity.
SEO title and meta description are passed using legacy product SEO fields when creating/updating products because they are still widely supported in Shopify REST payloads. If your store requires newer GraphQL-only fields later, you can swap that layer without changing the scraper.
