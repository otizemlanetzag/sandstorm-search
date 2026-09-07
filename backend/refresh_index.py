from __future__ import annotations

import argparse
from pathlib import Path

from .indexer import index

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SEEDS = ROOT / "data" / "index-seeds.txt"


def load_seeds(path: Path) -> list[str]:
    seeds: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip().lower()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("https://").removeprefix("http://").rstrip("/")
        if line and "/" not in line:
            seeds.append(line)
    return list(dict.fromkeys(seeds))


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh Sandstorm's search index from Common Crawl")
    parser.add_argument("--seeds", default=str(DEFAULT_SEEDS))
    parser.add_argument("--per-domain", type=int, default=10)
    parser.add_argument("--discovery-rounds", type=int, default=2)
    parser.add_argument("--discovery-limit", type=int, default=25)
    args = parser.parse_args()

    seeds = load_seeds(Path(args.seeds))
    if not seeds:
        raise SystemExit("No index seeds configured")

    domains = list(seeds)
    for domain in domains:
        pattern = f"{domain}/*"
        print(f"\n=== indexing {pattern} ===")
        index(pattern, max(1, args.per_domain), discover=True)

    # Grow within the seeded domains by following links that Common Crawl
    # has captures for. We deliberately keep the number of rounds bounded.
    for round_no in range(1, max(0, args.discovery_rounds) + 1):
        print(f"\n=== discovery round {round_no} ===")
        new_links: set[str] = set()
        for domain in domains:
            links = index(f"{domain}/*", max(1, args.discovery_limit), discover=True)
            new_links.update(links)
        print(f"discovery round {round_no}: {len(new_links)} candidate links")
        if not new_links:
            break

    print(f"refresh complete: {len(domains)} seeded domains")


if __name__ == "__main__":
    main()
