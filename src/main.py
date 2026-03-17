from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.config import Settings
from src.logger import get_logger
from src.scraper.client import FromuthHttpClient
from src.scraper.discover import ProductDiscoverer
from src.scraper.product_parser import ProductParser
from src.shopify.client import ShopifyClient
from src.sync.orchestrator import SyncOrchestrator
from src.sync.serializers import products_to_json, sync_results_to_json
from src.utils import write_json

logger = get_logger(__name__)


def main() -> None:
    settings = Settings.from_env()
    if not settings.fromuth_start_urls:
        raise SystemExit("FROMUTH_START_URLS is required.")

    client = FromuthHttpClient(settings)
    discoverer = ProductDiscoverer(client)
    parser = ProductParser()

    product_urls = discoverer.discover(
        settings.fromuth_start_urls,
        settings.max_products,
    )
    logger.info("Discovered %s product URLs", len(product_urls))

    products = []
    for url in product_urls:
        try:
            html = client.get_html(url)
            product = parser.parse(url, html)
            products.append(product)
        except Exception:
            logger.exception("Failed parsing %s", url)

    write_json(Path("data/products.json"), products_to_json(products))
    logger.info("Wrote data/products.json with %s products", len(products))

    shopify = ShopifyClient(settings)
    orchestrator = SyncOrchestrator(shopify, dry_run=settings.dry_run)
    results = orchestrator.run(products)

    write_json(Path("data/sync_results.json"), sync_results_to_json(results))
    logger.info("Wrote data/sync_results.json")

    if results.summary:
        logger.info("Summary: %s", results.summary)


if __name__ == "__main__":
    main()