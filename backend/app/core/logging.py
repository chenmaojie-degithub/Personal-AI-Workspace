from __future__ import annotations

import logging


def configure_logging() -> None:
    # Keep it simple for the initial skeleton.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    # ChromaDB sometimes logs telemetry transport errors that do not affect requests.
    # Silence these to avoid confusing "ERROR" noise in local dev and demos.
    for noisy in [
        "chromadb.telemetry",
        "chromadb.telemetry.product.posthog",
        "posthog",
    ]:
        logging.getLogger(noisy).setLevel(logging.CRITICAL)
