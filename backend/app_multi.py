"""
app_multi.py
------------
FastAPI for the multi-agent + human-in-the-loop demo.

Two SSE endpoints because HITL is two-phase:
  GET /api/analyze?ticker=RELIANCE&thread=<uuid>
      → streams agent steps, stops at an {approval_request}
  GET /api/resume?thread=<uuid>&decision=approve|reject|<feedback text>
      → resumes the SAME run (matched by thread id) and streams the outcome

Run:  uvicorn app_multi:app --reload --port 8000
"""

import json
import os

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agent_multi import start_run, resume_run
from chat_agent import run_chat
from agent_task import start_task, step_task
import companies
import docstore

app = FastAPI(title="Multi-Agent Equity Desk (HITL)")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


@app.get("/api/analyze")
async def analyze(ticker: str, thread: str):
    async def stream():
        try:
            async for ev in start_run(ticker, thread):
                yield sse(ev)
        except Exception as e:
            yield sse({"type": "error", "text": str(e)})
        yield sse({"type": "done"})
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/resume")
async def resume(thread: str, decision: str):
    async def stream():
        try:
            async for ev in resume_run(thread, decision):
                yield sse(ev)
        except Exception as e:
            yield sse({"type": "error", "text": str(e)})
        yield sse({"type": "done"})
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/task/start")
async def task_start(ticker: str, task: str, thread: str):
    async def stream():
        try:
            async for ev in start_task(ticker, task, thread):
                yield sse(ev)
        except Exception as e:
            yield sse({"type": "error", "text": str(e)})
        yield sse({"type": "done"})
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/task/step")
async def task_step(thread: str, decision: str):
    async def stream():
        try:
            async for ev in step_task(thread, decision):
                yield sse(ev)
        except Exception as e:
            yield sse({"type": "error", "text": str(e)})
        yield sse({"type": "done"})
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/chat")
async def chat(ticker: str, q: str, thread: str):
    async def stream():
        try:
            async for ev in run_chat(ticker, q, thread):
                yield sse(ev)
        except Exception as e:
            yield sse({"type": "error", "text": str(e)})
        yield sse({"type": "done"})
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/symbols")
async def symbols(q: str = ""):
    """Autocomplete for the search bar: company names + NSE tickers."""
    return {"results": companies.search(q, limit=8)}


@app.post("/api/upload")
async def upload(thread: str = Form(...), file: UploadFile = File(...)):
    """Attach a PDF / Word / text document to a chat thread for Q&A."""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(raw) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 15 MB).")
    try:
        text = docstore.extract_text(file.filename, raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    meta = docstore.add_document(thread, file.filename, text)
    return {"ok": True, **meta}


@app.delete("/api/upload")
async def upload_clear(thread: str):
    docstore.clear(thread)
    return {"ok": True}


@app.get("/api/health")
async def health():
    return {"ok": True, "has_key": bool(os.environ.get("GROQ_API_KEY")),
            "langsmith": bool(os.environ.get("LANGCHAIN_API_KEY"))}
