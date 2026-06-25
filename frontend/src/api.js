// Base URL of the FastAPI backend.
// Local dev: defaults to localhost:8000.
// Production (Vercel): set VITE_API_BASE to your Render backend URL,
//   e.g. https://mumpy-demo-api.onrender.com
export const API = import.meta.env.VITE_API_BASE || "http://localhost:8000";
