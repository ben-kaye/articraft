# Viewer

Web viewer for generated records under `data/records/`. List + 3D URDF view +
joint sliders + code/metadata inspector.

## Run (single command)

Builds the frontend if stale, launches the backend, opens the browser:

```bash
viewer/run.sh                           # add --no-open to stay headless
```

## Dev (HMR)

For live frontend reloads, run the two halves separately — Vite proxies `/api`:

```bash
uv run python -m viewer.server          # backend :8000
cd viewer/web && npm run dev            # frontend, open the port it prints
```

## Endpoints
- `GET /api/records?q=` — search (FTS via `data/index.db`); empty `q` → recent.
- `GET /api/records/{id}` — full record + `model_py` + provenance.
- `GET /api/records/{id}/files/{path}` — serve `model.urdf`, `assets/meshes/*.glb`.
