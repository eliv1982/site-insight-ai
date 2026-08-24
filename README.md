# Site Insight AI

Site Insight AI is a focused web application that fetches one public HTML page, extracts its readable text, and returns a validated, structured analysis from a single LLM call. The result describes what the page says; it does not inspect the rest of the site or verify the page's claims.

## What it does

1. Accepts the URL of one public webpage.
2. Validates and fetches the page with bounded, SSRF-aware network handling.
3. Removes scripts, styles, and HTML markup from the response.
4. Sends the bounded page text to an OpenAI-compatible API in one structured request.
5. Validates the model response with strict Pydantic models before returning it.

See [final_analyze_example.json](final_analyze_example.json) for an example response.

## What it does not do

This project is not a site-wide crawler, SEO audit, accessibility audit, security scanner, performance audit, visual-design audit, JavaScript-rendering browser, factual-verification engine, or traffic/reputation analytics service. It analyzes only the textual content available in the fetched HTML response for one page.

## Why this project matters

The project demonstrates several production-oriented concerns in a deliberately small application:

- safe ingestion of user-selected external web content;
- SSRF-aware URL and redirect validation;
- bounded downloads and bounded prompt input;
- a single structured LLM request rather than an open-ended agent loop;
- strict validation and rejection of malformed model output;
- non-root, read-only production containers with health and resource controls.

## Architecture

The frontend uses React 18 and Vite 7.3.6. The backend uses FastAPI, Pydantic v2, the OpenAI client, Requests, and BeautifulSoup.

```text
Browser
  -> frontend (Vite in development, nginx in production)
  -> same-origin /api
  -> FastAPI
  -> safe page fetch
  -> HTML-to-text cleanup
  -> one structured LLM analysis
  -> Pydantic-validated response
```

The browser sends `POST /api/llm/analyze-site`. The frontend proxy removes the `/api` prefix and forwards the request to the backend route `POST /llm/analyze-site`.

## Analysis output

Successful responses contain the normalized input `url` and a `final_analysis` object with these required fields:

| Field | Meaning |
| --- | --- |
| `summary` | Concise summary of the page text |
| `purpose` | Apparent purpose of the page, or an explicit uncertainty |
| `target_audience` | Likely audience, or an explicit uncertainty |
| `key_topics` | Topics supported by the page text |
| `offerings` | Explicitly presented products, services, or other offerings |
| `notable_claims` | Claims attributed to the page, not presented as verified facts |
| `content_strengths` | Strengths of the textual content |
| `content_gaps` | Missing, ambiguous, or unclear content |
| `analysis` | Overall analytical conclusion |

## Safety and security boundaries

- Only public `http` and `https` destinations on ports 80 and 443 are accepted.
- Local, private, reserved, link-local, and otherwise non-global resolved addresses are rejected.
- Redirects are followed manually, bounded, and revalidated at every hop.
- Only HTML/XHTML responses are accepted; response size, application-level fetch time, redirect count, and analysis text length are bounded.
- Non-identity content encodings are rejected so compressed responses cannot bypass the byte limit.
- Page URLs and text are serialized as untrusted prompt data, with explicit instructions not to follow instructions embedded in that data.
- Model output must match strict Pydantic types, fields, list sizes, and string limits.

These controls reduce SSRF and prompt-injection risk; they do not eliminate it. The total fetch budget is not a hard operating-system DNS deadline, and DNS validation and the later HTTP connection are separate operations. That leaves residual resolver-delay and DNS-rebinding/time-of-check-to-time-of-use risks. Infrastructure-level egress restrictions remain useful defense in depth for a production deployment.

## Local development

Prerequisites are Docker Engine and Docker Compose v2. Copy the backend environment template and replace its placeholders:

```sh
cp .env.example .env
docker compose up --build
```

The development stack publishes loopback-only ports:

- frontend Vite server: `http://127.0.0.1:5173`;
- backend API: `http://127.0.0.1:8000`;
- backend OpenAPI UI: `http://127.0.0.1:8000/docs`.

Vite proxies `/api` to the backend. Backend `--reload` and the Vite development server are development-only; neither is present in the production images.

Stop the development stack with `docker compose down`.

## Production/demo deployment

Production requires an external reverse proxy/TLS service and an existing shared Docker network. The production Compose file publishes no application ports: the proxy reaches frontend nginx on port 8080, while the backend remains internal on port 8000.

Images are built from the current clean checkout and share an explicit commit/release tag. See [DEPLOY.md](DEPLOY.md) for the controlled deployment, upgrade, rollback, and verification procedures.

## Environment variables

Backend runtime values belong in `.env`:

| Variable | Role |
| --- | --- |
| `OPENAI_API_KEY` | Canonical OpenAI-compatible provider credential |
| `API_KEY` | Compatibility fallback when `OPENAI_API_KEY` is absent |
| `BASE_URL` | Canonical OpenAI-compatible API base URL |
| `PROXY_API_URL` | Compatibility fallback when `BASE_URL` is absent |

The model is not selected by an environment variable; the current code default is `gpt-4o`.

The frontend also recognizes optional `VITE_API_URL` during development/build. When it is empty or unset—as in the committed development Compose configuration—the client uses the same-origin `/api` path. It is not a backend secret and does not belong in backend `.env`.

Deployment values belong in the invoking shell, CI job, or deployment environment—not in backend `.env`:

| Variable | Role |
| --- | --- |
| `PROXY_NETWORK` | Required name of the existing external proxy network |
| `IMAGE_TAG` | Optional for `deploy.sh`; defaults to the current 12-character Git `HEAD` |

An image tag labels the build of the current checkout. It does not select or roll back source code.

## Testing

Backend:

```sh
python -m pytest
```

The current suite contains 73 tests.

Frontend, using Node.js 24:

```sh
cd frontend
npm ci
npm run build
npm audit
npm audit --omit=dev
```

## Repository status and scope

This is a portfolio-ready, hardened course project with an intentionally narrow scope: structured analysis of one public webpage. Ideas such as crawling, browser rendering, audits, or analytics are not implemented features.
