# Infinity Snake Crawl

**Infinity Snake Crawl** is an advanced, open-source web crawler designed to run through a simple web control panel and work with a Vercel deployment.

The project includes two different crawling modes:

1. **Normal Crawl** — starts from a URL and follows links according to the selected limits.
2. **Advanced Discovery** — works differently from a traditional crawler: it generates a bounded set of domain candidates, tests them, and records reachable results.

The goal is to keep the crawler practical, understandable, and easy to deploy without requiring a permanent Python server.

## Features

### Normal Crawl

The regular crawler can:
- Start from any HTTP or HTTPS URL.
- Crawl multiple pages in batches.
- Follow discovered links.
- Limit the maximum crawl depth.
- Limit the total number of pages.
- Restrict crawling to the starting domain.
- Add a delay between batches.
- Record HTTP status and content information.
- Collect page titles, descriptions, text, links, depth, and crawl time.
- Export the collected results as DATA.CSV.

### Advanced Discovery

The Advanced Crawl engine is located in `Advanced_crawl/advanced_crawl.py`.

Unlike the normal crawler, it does not require a seed URL.

It can:
- Retrieve the current public TLD list from IANA.
- Generate a bounded number of domain candidates.
- Test candidates over HTTPS.
- Record successful HTTP responses.
- Extract readable text from HTML using Python's standard library.
- Handle connection failures and timeouts without stopping the whole batch.
- Export discovery results to CSV through the web interface.

The web interface exposes this mode as **Advanced Discovery**.

## Web Control Panel

The control panel provides separate tabs for the two crawler engines.

### Normal Crawl
- Start URL
- Maximum pages
- Maximum depth
- Pages per request
- Request delay
- Same-domain-only mode
- Start/Stop controls
- Progress statistics
- Activity log
- CSV download

### Advanced Discovery
- Total candidates
- Batch size
- Maximum generated domain-label length
- Delay between batches
- Start/Stop controls
- Tested count
- HTTP 200 count
- Error count
- Remaining candidates
- Activity log
- CSV download

## Authentication

The control panel is protected by a secret-code gate.

The authentication endpoint is `/api/auth`.

For deployment, the recommended approach is to store the secret as the Vercel environment variable `SNAKE_CRAWL_SECRET`.

Do not put a real production secret directly into a public Git repository.

## Project Structure

```text
snake-crawl/
├── Advanced_crawl/
│   ├── .gitkeep
│   └── advanced_crawl.py
├── api/
│   ├── advanced.py
│   ├── auth.py
│   └── crawl.py
├── DATA.CSV
├── index.html
├── requirements.txt
├── vercel.json
└── README.md
```

## Vercel Deployment

The project is designed for Vercel.

Basic deployment:
1. Fork or clone the repository.
2. Import the repository into Vercel.
3. Configure the `SNAKE_CRAWL_SECRET` environment variable.
4. Deploy.
5. Open the deployed site.
6. Enter the configured secret code.
7. Choose **Normal Crawl** or **Advanced Discovery**.

No persistent Python server is required for the web interface.

### Important architecture note

Vercel serverless functions are request-based. They are not intended to keep a Python crawler process running indefinitely in the background.

For that reason, Advanced Discovery runs in **bounded batches**. The browser requests one batch, waits for the configured delay, and requests the next batch.

This keeps the architecture compatible with Vercel while still allowing longer discovery runs.

## CSV Output

Normal Crawl exports:
- `url`
- `final_url`
- `status`
- `content_type`
- `title`
- `description`
- `text`
- `links`
- `depth`
- `crawled_at`

Advanced Discovery exports:
- `url`
- `final_url`
- `status`
- `content_type`
- `content`

## Responsible Crawling

Infinity Snake Crawl is designed around bounded requests rather than unlimited traffic.

When using the crawler against websites you do not operate, keep request rates reasonable and respect the target site's policies, robots.txt where applicable, and server capacity.

The Advanced Discovery engine intentionally limits the number of candidates processed per request.

## License / Project Notice

This repository is part of the Infinity project and is described as a non-commercial web crawler.

Check the repository's current license and project files before redistributing or deploying modified versions.

## Status

Infinity Snake Crawl is an actively developed project.

The crawler architecture can be expanded with additional discovery strategies, indexing, scheduling, storage backends, and crawler engines over time.
## Licensing

This repository uses two different licenses for different categories of material:

- **DATA.CSV** is licensed under **INFINITY ODL (INFINITY Open Data License)**. See [INFINITY ODL LICENSE.md](./INFINITY%20ODL%20LICENSE.md).
- **All other project files** are licensed under **INFINITY GOSL (Infinity General Open Source License)**. See [INFINITY GOSL LICENSE.md](./INFINITY%20GOSL%20LICENSE.md).

The two licenses apply to their respective materials only. The license for DATA.CSV does not grant rights to the source code, and the source-code license does not replace the data license.