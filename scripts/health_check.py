"""Check that every Argus service is up and responsive.

Hits each service's /health endpoint (lighter and more meaningful than /docs).
Exit code 0 if all green, 1 otherwise — usable in CI or a pre-demo check.

Usage:  python scripts/health_check.py
"""
import asyncio
import sys

import httpx

SERVICES = {
    # Providers
    "Maigret Provider": 8020,
    "Moriarty Provider": 8021,
    "Telegram Provider": 8022,
    "Reddit Provider": 8023,
    "Holehe Provider": 8024,
    "WhatsApp Provider": 8025,
    "Yandex Image Provider": 8026,
    "WhatsMyName Provider": 8027,
    "Ignorant Provider": 8028,
    "Social Analyzer Provider": 8029,
    "GHunt Provider": 8030,
    # Analyzers
    "Username Analyzer": 8010,
    "Facial Analyzer": 8011,
    "Text Analyzer": 8012,
    "Timing Analyzer": 8013,
    "Contacts Analyzer": 8014,
    "Content Profiler": 8015,
    "Image Similarity": 8016,
    "Face Pipeline": 8017,
    "Image Metadata": 8018,
}


async def check_one(client: httpx.AsyncClient, name: str, port: int) -> bool:
    url = f"http://localhost:{port}/health"
    try:
        resp = await client.get(url)
        ok = resp.status_code == 200
        extra = ""
        if ok:
            body = resp.json()
            # Surface useful health flags (model loaded, mode, etc.).
            flags = {k: v for k, v in body.items() if k not in ("status", "service")}
            if flags:
                extra = "  " + " ".join(f"{k}={v}" for k, v in flags.items())
        mark = "OK " if ok else f"DOWN ({resp.status_code})"
        print(f"  [{mark:>10}]  {name:<20} :{port}{extra}")
        return ok
    except Exception:
        print(f"  [{'UNREACHABLE':>10}]  {name:<20} :{port}")
        return False


async def main() -> int:
    print("Argus health check\n" + "-" * 50)
    async with httpx.AsyncClient(timeout=5) as client:
        results = await asyncio.gather(
            *(check_one(client, n, p) for n, p in SERVICES.items())
        )
    up = sum(results)
    total = len(SERVICES)
    print("-" * 50)
    print(f"{up}/{total} services healthy")
    return 0 if up == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
