# Sandstorm Search

An open-source search engine prototype whose web index is built from [Common Crawl](https://commoncrawl.org/) crawl data.

## Architecture

### Local development

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

### Netlify deployment

```text
SQLite FTS5 index (built locally)
       ↓
backend/export_index.py
       ↓
public/index.json
       ↓
Netlify static site
       ↓
Netlify Function: search
```

Private encrypted notes use Netlify Blobs as opaque ciphertext storage. The browser keeps the AES-256-GCM session key; it is never sent to Netlify.

## Netlify

The repository is configured for Netlify with `netlify.toml`.

1. Connect this GitHub repository to a new Netlify site.
2. Netlify will use `public` as the published directory and `netlify/functions` for serverless functions.
3. The build command runs `python -m backend.export_index`.
4. If `data/search.db` exists during the build, it is exported to `public/index.json`. If it does not exist, the existing index file is preserved.
5. Netlify Functions provide `/search`, `/api/search`, and `/api/private/blobs`.

Netlify Blobs must be available to the site for private encrypted storage. The required `@netlify/blobs` dependency is already included in `package.json`.

## Building a public index

Build a local Common Crawl index first, for example:

```bash
python -m backend.indexer "example.com/*" --limit 20
```

Then export it for Netlify:

```bash
python -m backend.export_index
```

Commit the resulting `public/index.json` and push it to GitHub. Netlify will then deploy that index.

For a serious public search engine, the index should eventually be stored in a dedicated search/database service rather than shipping the entire corpus as one JSON file. Netlify Functions have a synchronous execution limit, so large-scale Common Crawl ingestion should run as a separate background/indexing process. Netlify supports background functions for longer-running jobs. 

## Important

Common Crawl is used as the source of crawled pages. Sandstorm does **not** download the entire Common Crawl corpus: the indexer asks a Common Crawl index for matching URLs, downloads the corresponding WARC byte ranges, extracts HTML text, and stores only the searchable fields locally.

The Netlify search function searches the exported index with a lightweight relevance scorer. The local FastAPI implementation remains available for development and larger local indexes.

## License

GPL-3.0-or-later. See `LICENSE`.
