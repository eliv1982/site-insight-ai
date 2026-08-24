# Deployment

This guide describes the current production/demo workflow for Site Insight AI. It builds explicitly tagged application images from a trusted Git checkout and connects them to an externally managed reverse proxy. It does not use a registry-driven `latest` workflow or unattended updates.

## Architecture

```text
Internet
  -> external reverse proxy / TLS (Traefik, Caddy, or equivalent)
  -> frontend nginx :8080
  -> same-origin /api
  -> backend FastAPI :8000
```

`docker-compose.deploy.yml` defines exactly two application services:

- `frontend` joins the private application bridge and the external proxy network;
- `backend` joins only the application bridge;
- neither service publishes an application port on the host.

The application bridge is intentionally a normal outbound-capable Docker bridge because the backend must reach public webpages and the configured LLM provider. The external proxy and its TLS configuration are outside this repository.

## Prerequisites

- A Linux server with Docker Engine and Docker Compose v2.
- Git.
- An existing external reverse proxy with TLS configured for the application hostname.
- An existing external Docker network shared by that proxy and the application frontend.
- SSH access to the server; a non-root account and key-based authentication are recommended.

No Docker Hub account or application-port firewall rule is required by this workflow.

## Clone or update the checkout

Clone the repository into a deployment directory:

```sh
git clone https://github.com/OWNER/site-insight-ai.git
cd site-insight-ai
```

For an existing checkout, select a trusted branch, tag, or commit before deploying:

```sh
git fetch --prune origin
git switch main
git pull --ff-only origin main
git status --short
```

The final status command must produce no output. Deployment images are built from exactly the files in the current checkout.

## Backend environment

Create the backend runtime file from the committed template:

```sh
cp .env.example .env
chmod 600 .env
```

Edit `.env` and replace its placeholders with the OpenAI-compatible provider values for this deployment. The file contains backend runtime configuration and secrets only. It is ignored by Git, must never be committed, and should remain readable only by the deployment account where practical.

Do not put `PROXY_NETWORK` or `IMAGE_TAG` in `.env`. They are deployment inputs supplied through the invoking shell, CI job, or deployment environment. `deploy.sh` checks that `.env` exists but does not source or print it.

## Deployment variables

### `PROXY_NETWORK`

Required. This is the name of the existing external Docker network used by the reverse proxy:

```sh
export PROXY_NETWORK=proxy-network-name
docker network inspect "$PROXY_NETWORK"
```

The deployment script validates the name and stops if the network does not exist.

### `IMAGE_TAG`

Optional when using `deploy.sh`. If omitted, the script derives the current 12-character Git `HEAD`:

```sh
unset IMAGE_TAG
```

An explicit release tag can be supplied when required:

```sh
export IMAGE_TAG=release-1
```

Both backend and frontend images receive the same tag. `IMAGE_TAG` identifies a build of the current checkout; it does not select a Git revision or change the files being built.

## Reverse proxy integration

Attach the external reverse-proxy container to the same Docker network named by `PROXY_NETWORK`. Configure the proxy to route the application's HTTPS hostname to the `frontend` service on port 8080.

The reverse proxy owns public HTTP/HTTPS listeners, certificates, and TLS policy. The backend must not be exposed or targeted directly. Browser API calls remain same-origin under `/api`; frontend nginx forwards those requests to the internal `backend:8000` service.

Provider-specific labels and proxy configuration intentionally remain outside this repository.

## Deploy

With `.env` present, `PROXY_NETWORK` exported, and the checkout clean, run:

```sh
bash ./deploy.sh
```

If deployment packaging has made the script executable, `./deploy.sh` is equivalent. The repository currently tracks the script as a regular non-executable file, so invoking it through Bash avoids changing the clean checkout's file mode.

The script:

1. enables strict shell behavior;
2. verifies Git, Docker, Compose v2, `.env`, and the production Compose file;
3. validates `PROXY_NETWORK` and an optional explicit `IMAGE_TAG`;
4. derives `IMAGE_TAG` from the current 12-character `HEAD` when absent;
5. rejects a dirty working tree;
6. verifies the external proxy network;
7. builds backend and frontend images from the current checkout;
8. runs `docker compose ... up -d --wait`;
9. reports final service status.

It does not pull `latest`, perform unattended updates, or run `docker compose down` first.

## Health verification

Direct Compose commands must receive the same deployment values used for the release. If the default tag was used, set it in the current shell before running them:

```sh
export IMAGE_TAG="$(git rev-parse --short=12 HEAD)"
export PROXY_NETWORK=proxy-network-name
```

Check status and recent service logs:

```sh
docker compose -f docker-compose.deploy.yml ps
docker compose -f docker-compose.deploy.yml logs --tail=100 backend
docker compose -f docker-compose.deploy.yml logs --tail=100 frontend
```

The services also provide dependency-free container-local health endpoints:

```sh
docker compose -f docker-compose.deploy.yml exec backend python -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8000/health").read().decode())'
docker compose -f docker-compose.deploy.yml exec frontend wget -qO- http://127.0.0.1:8080/health
```

After the external proxy is configured, verify the public frontend health and same-origin backend path through that proxy:

```sh
curl -fsS https://your-app.example/health
curl -fsS https://your-app.example/api/health
```

Because the production Compose file publishes no host application ports, do not test it through public host ports 8080 or 8000.

## Upgrade

Choose and check out the trusted revision first, confirm the tree is clean, and then deploy that checkout:

```sh
git fetch --prune origin
git switch main
git pull --ff-only origin main
git status --short
export PROXY_NETWORK=proxy-network-name
unset IMAGE_TAG
bash ./deploy.sh
```

For a trusted tag or commit, check it out instead of pulling `main`. The deploy script rebuilds the two images, updates the services in place, and waits for service health.

## Rollback

1. Identify the previous known-good commit or signed/trusted tag.
2. Check out that revision.
3. Confirm `git status --short` is empty.
4. Keep `PROXY_NETWORK` set to the deployment's existing proxy network.
5. Run `bash ./deploy.sh` so the previous checkout is rebuilt and started.

For example:

```sh
git fetch --prune origin
git switch --detach KNOWN_GOOD_COMMIT
git status --short
export PROXY_NETWORK=proxy-network-name
export IMAGE_TAG="$(git rev-parse --short=12 HEAD)"
bash ./deploy.sh
```

Setting `IMAGE_TAG` alone is not a rollback. It only names images built from the files currently checked out; the source revision must be changed first.

## Logs, status, and restart

With the deployment variables set as described under health verification:

```sh
docker compose -f docker-compose.deploy.yml ps
docker compose -f docker-compose.deploy.yml logs --tail=100 --follow backend
docker compose -f docker-compose.deploy.yml logs --tail=100 --follow frontend
```

Prefer targeted operations over stopping the whole stack:

```sh
docker compose -f docker-compose.deploy.yml restart backend
docker compose -f docker-compose.deploy.yml up -d --wait --force-recreate frontend
```

For a source or image change, use the controlled deployment script rather than manually tearing the stack down.

## Firewall and security boundary

- Expose only the reverse proxy's public HTTP/HTTPS ports as required.
- Restrict SSH to appropriate source networks and use key-based authentication where possible.
- Do not publish application ports 8080 or 8000 from this Compose stack.
- Do not attach the backend to the external proxy network.
- Keep `.env` backend-only and never make its secrets available to the frontend or reverse proxy.
- Consider infrastructure-level outbound filtering as additional defense against residual DNS-rebinding/TOCTOU risk.

The production services run non-root with read-only filesystems, limited tmpfs storage, all capabilities dropped, `no-new-privileges`, healthchecks, PID/resource limits, and bounded Docker logs.

## Updates

Releases are deliberate and manual. The former hourly updater and cron mechanism have been removed. The deployment does not pull mutable `latest` images; each release builds both images from the selected clean checkout under one explicit tag.

## Troubleshooting

### `PROXY_NETWORK is required`

Export the existing external network name in the same shell that invokes the deployment:

```sh
export PROXY_NETWORK=proxy-network-name
```

### External proxy network does not exist

Confirm the name and ensure the reverse-proxy stack created the network:

```sh
docker network inspect "$PROXY_NETWORK"
```

Do not silently create a differently named network; the proxy and frontend must share the same one.

### Missing backend environment file

Create `.env` from `.env.example`, replace the placeholders, and restrict its permissions. Do not put deployment variables in that file.

### Dirty working tree

Inspect `git status --short`. Commit intended source changes or restore/stash local tracked changes before deployment. Do not bypass the clean-checkout guard.

### Backend or frontend is unhealthy

Use Compose status and service logs. Backend `/health` is process-local and does not call a webpage or the LLM. Frontend `/health` is served directly by nginx.

### Proxy cannot reach frontend

Confirm the proxy and frontend are attached to the network named by `PROXY_NETWORK`, then confirm the proxy target is the frontend service on port 8080. Do not add a host port as a workaround.

### Frontend cannot resolve backend

The backend Compose service must remain named `backend`, and both services must share the application network. From frontend, test the internal route:

```sh
docker compose -f docker-compose.deploy.yml exec frontend wget -qO- http://backend:8000/health
```

### Long analyses time out at the external proxy

The browser client and frontend nginx allow up to 300 seconds for analysis traffic. Configure the external proxy's upstream timeout consistently with that limit while retaining appropriate global limits. Do not remove timeouts entirely.
