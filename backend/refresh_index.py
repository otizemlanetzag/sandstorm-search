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
    args = parser.parse_args()

    seeds = load_seeds(Path(args.seeds))
    if not seeds:
        raise SystemExit("No index seeds configured")

    for domain in seeds:
        pattern = f"{domain}/*"
        print(f"\n=== indexing {pattern} ===")
        index(pattern, max(1, args.per_domain))

    print(f"refresh complete: {len(seeds)} domains")


if __name__ == "__main__":
    main()
