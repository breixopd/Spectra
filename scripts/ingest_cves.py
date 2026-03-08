"""
CVE Ingestion Script.

Loads NVD JSON feeds from cve_data/ directory, generates embeddings,
and stores them for RAG retrieval.
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from app.services.ai.rag import Document
from scripts import init_script_services

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("spectra.scripts.ingest_cves")

CVE_DATA_DIR = Path("cve_data")


async def load_cve_data(file_path: Path) -> list[dict[str, Any]]:
    """Load and parse a single NVD JSON file."""
    logger.info("Loading %s...", file_path)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        cve_items = data.get("CVE_Items", [])
        processed_cves = []

        for item in cve_items:
            cve_id = item["cve"]["CVE_data_meta"]["ID"]
            description_data = item["cve"]["description"]["description_data"]
            description = next(
                (d["value"] for d in description_data if d["lang"] == "en"), ""
            )

            if description:
                processed_cves.append(
                    {
                        "id": cve_id,
                        "description": description,
                        "metadata": {"year": file_path.stem.split("-")[-1], "source": "nvd"},
                    }
                )

        logger.info("Parsed %d CVEs from %s", len(processed_cves), file_path.name)
        return processed_cves

    except Exception as e:
        logger.error("Failed to load %s: %s", file_path, e)
        return []


async def main():
    """Main ingestion loop."""
    logger.info("Starting CVE ingestion...")

    # Initialize common services
    rag = await init_script_services()

    # Find all JSON files
    files = sorted(CVE_DATA_DIR.glob("nvdcve-1.1-*.json"))
    if not files:
        logger.warning("No CVE data found in %s", CVE_DATA_DIR)
        return

    total_cves = 0

    for file_path in files:
        cves = await load_cve_data(file_path)
        if not cves:
            continue

        # Process in batches
        batch_size = 100
        for i in range(0, len(cves), batch_size):
            batch = cves[i : i + batch_size]

            # Create Document objects
            docs = []
            for c in batch:
                doc = Document(
                    id=c["id"],
                    content=c["description"],
                    doc_type="cve",
                    metadata=c["metadata"],
                    cve_id=c["id"],
                    severity="unknown",  # NVD doesn't include severity in basic data
                    target=None,
                    session_id=None,
                )
                docs.append(doc)

            try:
                await rag.index_batch(docs)
                total_cves += len(batch)
                if i % 1000 == 0:
                    logger.info("Indexed %d CVEs...", total_cves)
            except Exception as e:
                logger.error("Failed to index batch: %s", e)

    logger.info("Ingestion complete. Total CVEs indexed: %d", total_cves)


if __name__ == "__main__":
    asyncio.run(main())
