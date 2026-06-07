# Traefik — Reverse Proxy

## Role

Single entry point for all HTTP traffic on the developer machine. Routes `*.localhost` hostnames to the appropriate Docker container without requiring any manual port mapping beyond `:80`.

## Configuration

Traefik runs in Docker-provider mode: it watches the Docker socket and automatically discovers services via container labels. No static config file is needed.

```yaml
# docker-compose.yml (relevant excerpt)
command:
  - --api.insecure=true          # exposes the dashboard on :8080
  - --providers.docker=true      # watches /var/run/docker.sock
  - --providers.docker.exposedbydefault=false   # opt-in per container
  - --entrypoints.web.address=:80
ports:
  - "80:80"    # all *.localhost traffic
  - "8080:8080"  # Traefik dashboard
```

## Routing Table

Each service opts in with `traefik.enable=true` and declares its hostname rule via labels:

| Hostname | Target service | Container port |
|---|---|---|
| `app.localhost` | frontend | 3000 |
| `api.localhost` | api | 8000 |
| `openviking.localhost` | openviking | 1933 |
| `qdrant.localhost` | qdrant | 6333 |

The `marker` service has `traefik.enable=false` — it is internal only, reached by the API over the Docker network as `http://marker:8001`.

## WebSocket middleware

The OpenViking router has a custom middleware that sets `X-Forwarded-Proto: http`. This is required for the OpenViking dashboard WebSocket handshake to succeed through the proxy:

```yaml
- traefik.http.middlewares.openviking-ws.headers.customrequestheaders.X-Forwarded-Proto=http
- traefik.http.routers.openviking.middlewares=openviking-ws
```

## Dashboard

Available at **http://localhost:8080** while the stack is running. Shows all detected routers, services, and middlewares. Useful for debugging routing rules.

## Network

All containers share the `app_net` bridge network. Traefik reaches container services by their Docker service name (e.g. `openviking:1933`). The host machine reaches everything through Traefik on port 80.
