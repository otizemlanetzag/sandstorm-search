# Sandstorm Search

An open-source search engine prototype whose web index is built from [Common Crawl](https://commoncrawl.org/) crawl data.

## Architecture

```text
Common Crawl Index
       ↓
backend/indexer.py
       ↓
WARC HTML extraction
       ↓
SQLite FTS5 index
       ↓
backend/main.py
       ↓
Web search UI / JSON API
```

Common Crawl is used as the source of crawled pages. Sandstorm does **not** download the entire Common Crawl corpus: the indexer asks a Common Crawl index for matching URLs, downloads the corresponding WARC byte ranges, extracts HTML text, and stores only the searchable fields locally.

## Run

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Build a small test index. For example:

```bash
python -m backend.indexer "example.com/*" --limit 20
```

Start the search server:

```bash
python -m uvicorn backend.main:app --reload
```

Then open `http://127.0.0.1:8000`.

## Important

The default Common Crawl index in `backend/indexer.py` is a configurable crawl identifier. For production, update it to the crawl you want to process and implement incremental checkpoints, retries, deduplication, robots/policy handling, and a larger search backend before attempting a large-scale crawl.

## License

GPL-3.0-or-later. See `LICENSE`.
