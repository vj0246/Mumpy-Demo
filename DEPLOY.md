# Deploying (Vercel + Render)

This app is **two pieces** that must both be hosted:

| Piece | What | Host | Why there |
|---|---|---|---|
| `frontend/` | React + Vite static site | **Vercel** | static hosting, instant CDN |
| `backend/`  | FastAPI + agents + yfinance | **Render** | needs one always-on Python process (in-memory HITL state, SSE streaming, yfinance) |

> A backend **is** required: the Groq key must stay server-side, and yfinance,
> the LangGraph agents and PDF/Word parsing are all Python. The browser can't do
> any of that. Vercel hosts the frontend; the backend runs on Render.

The repo already contains everything needed: `render.yaml` (backend blueprint),
`frontend/vercel.json`, and the frontend reads the backend URL from
`VITE_API_BASE`.

---

## 1. Backend → Render (do this first; you need its URL for step 2)

1. Push this repo to GitHub (already at `vj0246/Mumpy-Demo`).
2. Go to <https://dashboard.render.com> → **New** → **Blueprint**.
3. Select the **Mumpy-Demo** repo. Render reads `render.yaml` and proposes a web
   service called **mumpy-demo-api**.
4. It will ask for the **GROQ_API_KEY** env var — paste your `gsk_...` key.
   (It's marked `sync: false`, so it's never stored in git.)
5. Click **Apply**. First build takes a few minutes.
6. When it's live, copy the URL, e.g. `https://mumpy-demo-api.onrender.com`.
   Check `https://<that-url>/api/health` → should return `{"ok": true, ...}`.

**Free-tier note:** the service **sleeps after ~15 min idle**; the next request
wakes it (~30–60s cold start). Fine for a demo. To avoid sleeps, upgrade the
Render plan or ping `/api/health` every few minutes.

---

## 2. Frontend → Vercel

1. Go to <https://vercel.com/new> → import the **Mumpy-Demo** repo.
2. **Root Directory** → set to **`frontend`** (important — the repo root has both
   folders). Vercel auto-detects Vite (build `npm run build`, output `dist`).
3. **Environment Variables** → add:
   - `VITE_API_BASE` = your Render URL from step 1 (no trailing slash),
     e.g. `https://mumpy-demo-api.onrender.com`
   > Vite bakes env vars in **at build time**, so set this *before* the first
   > deploy. If you change it later, redeploy.
4. **Deploy.** You'll get a URL like `https://mumpy-demo.vercel.app`.

---

## 3. That's it

Open the Vercel URL. The frontend calls the Render backend over HTTPS. CORS is
already open (`allow_origins=["*"]` in `app_multi.py`), so no extra config.

### Things to know in production
- **First load after idle is slow** — Render free tier cold start (above).
- **Uploaded documents live in memory**, keyed by chat thread. They're lost when
  the Render service sleeps/restarts. Re-upload after a cold start. (For
  persistence you'd add a store like S3/Redis — out of scope for the demo.)
- **yfinance from a datacenter IP** can be throttled by Yahoo more than locally.
  The backend already retries with a browser-impersonating session; if a fetch
  flakes, retry. Seeded tickers (RELIANCE, TCS, INFY, …) always work offline.
- **Updating:** push to `main` → Render and Vercel both auto-redeploy.
