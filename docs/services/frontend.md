# Frontend — Chat UI

## Role

Serves the static chat interface and the demo viewer. There is no server-side rendering — all logic runs in vanilla JavaScript in the browser. The frontend container is purely nginx serving static files.

## Image

Built from `frontend/Dockerfile`:

```dockerfile
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY static/ /usr/share/nginx/html/
EXPOSE 3000
```

Static files are baked into the image at build time. Any change to `frontend/static/` requires a `docker compose build frontend && docker compose up -d frontend` to take effect.

## Pages

| URL | File | Description |
|---|---|---|
| `http://app.localhost/` | `index.html` | Live chat UI |
| `http://app.localhost/demo.html` | `demo.html` | Pre-generated demo viewer |

## File structure

```
frontend/static/
├── index.html       # Chat UI shell
├── demo.html        # Demo viewer (keyboard navigable, ← →)
├── app.js           # Chat UI logic — SSE streaming, markdown rendering
├── style.css        # Shared styles (light mode, source cards, thinking indicator)
└── demo_data.json   # Pre-generated Q&A results (written by make demo-prep)
```

## SSE streaming (`app.js`)

The chat UI connects to `POST /query` and reads the response as a raw byte stream:

```
reader = response.body.getReader()
```

SSE lines are parsed manually (not via `EventSource`) to support streaming over the same origin without CORS. Key parsing detail: exactly one leading space is stripped from each `data:` field per the SSE spec — `line.slice(5).replace(/^ /, "")` — preserving content-meaningful spaces in LLM tokens.

Tokens are accumulated in a `fullText` string and the full string is re-rendered on every token. This ensures Markdown patterns like `**bold**` render correctly even when the `**` markers arrive in separate token events.

## Demo viewer (`demo.html`)

Loads `demo_data.json` on page load and renders one Q&A card at a time. Navigate with `←` / `→` arrow keys or the Prev/Next buttons. Each card shows the question, answer (with Markdown rendering), elapsed time, and collapsible source references.

To regenerate `demo_data.json`:

```bash
make demo-prep   # runs scripts/demo_prep.py against the live API
```

After regeneration, rebuild the frontend image so the new data is baked in:

```bash
docker compose build frontend && docker compose up -d frontend
```

## Markdown rendering

A minimal in-browser renderer handles the subset of Markdown the LLM produces:

```javascript
function renderMarkdown(text) {
  return text
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br/>");
}
```

Tables and bullet lists from the LLM are rendered as plain text (pre-wrap). This is intentional — a full Markdown library would add significant weight for marginal gain on this use case.

## nginx config

Listens on port 3000, serves files from `/usr/share/nginx/html`, with `try_files $uri $uri/ =404` (no SPA routing needed — all pages are static HTML files).
