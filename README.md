# Agentic Equity Desk + Chat

A live, agentic AI demo for the Mumbai Python Developers Group, built around one idea:
**an LLM that can plan, use tools, and act, with a human in the loop.**

Two things share one screen:

- **The Analyst Agent** (left) — a task-driven agent with **step-by-step
  human-in-the-loop**. You give it a stock and a task (presets or free text). It
  proposes **one step at a time** ("I'll pull news and gauge sentiment, OK?"); you
  **Approve / Redirect / Stop**. It acts only with your sign-off, then proposes the
  next step. Answers are grounded in fetched data, never invented.
- **The Chat** (right side panel) — a conversational ReAct agent. Type any NSE
  stock symbol and ask anything (sentiment, news, fundamentals, splits, a chart if
  available). It decides which tools to call and can invoke the desk pipeline.

Agentic AI is the focus; generative AI shows up inside the tools (news sentiment,
summaries, reports). Live data comes from yfinance (NSE); the three bundled tickers
(RELIANCE, TCS, INFY) are cached as an offline fallback. Charts are optional — if
price data can't be fetched, the agent keeps going with news and analysis.

## Architecture

```
                         ┌──────────────── FRONTEND (React + Vite) ───────────────┐
                         │  App.jsx                                                │
                         │   ├─ Desk.jsx   left   : multi-agent + HITL (SSE)        │
                         │   └─ Chat.jsx   right  : ReAct chat agent (SSE)          │
                         │        └─ Chart.jsx    : recharts price chart            │
                         └────────────────────────────┬───────────────────────────┘
                                                       │  Server-Sent Events
                         ┌─────────────────────────────┴──────────────────────────┐
                         │  app_multi.py  (FastAPI)                                 │
                         │   /api/analyze + /api/resume  -> the Desk (HITL)         │
                         │   /api/chat                   -> the Chat agent          │
                         └───────┬───────────────────────────────┬─────────────────┘
                                 │                                │
                   ┌─────────────┴──────────┐        ┌────────────┴───────────────┐
                   │ agent_multi.py          │        │ chat_agent.py               │
                   │  StateGraph desk:       │        │  ReAct agent (LangGraph     │
                   │  gather→researcher→     │        │  prebuilt) with 6 tools,    │
                   │  risk_check→synthesize  │◄───────┤  one of which RUNS THE DESK │
                   │  + HITL via _pending    │  tool  │  (deep_desk_analysis)       │
                   └─────────────┬───────────┘        └────────────┬───────────────┘
                                 │                                 │
                                 └──────────────┬──────────────────┘
                                                │
                                       ┌────────┴─────────┐
                                       │ market.py         │
                                       │ yfinance (NSE)    │
                                       │ + cache + mock    │
                                       │   fallback        │
                                       └────────┬─────────┘
                                                │
                                          data/*.json  (RELIANCE, TCS, INFY samples)
```

## Backend files

```
backend/
  market.py        yfinance NSE data layer: quote, price/chart, fundamentals,
                   news, splits. Bundle cached 5 min; the live spot quote has its
                   own ~20s cache so the price stays current while markets are open.
                   Falls back to data/*.json for the sample tickers if live fails.
  companies.py     NSE company directory (name + ticker) behind the search-bar
                   autocomplete (/api/symbols).
  docstore.py      uploaded-document store: extracts text from PDF (pypdf) / Word
                   (python-docx) / text, chunks it, and does keyword retrieval for
                   the chat's ask_document tool. In-memory, keyed by chat thread.
  agent_task.py    the ANALYST: task-driven agent with step-by-step HITL. Proposes
                   one step, waits for Approve / Redirect / Stop, executes, repeats.
                   Grounded in real data; never invents numbers.
  chat_agent.py    the CHAT: a LangGraph prebuilt ReAct agent with six tools,
                   tightened to answer only from tool results.
  agent_multi.py   older multi-agent desk pipeline (kept; chat can call it).
  app_multi.py     FastAPI. SSE endpoints:
                     /api/task/start, /api/task/step   -> Analyst (step HITL)
                     /api/chat                          -> Chat
                     /api/symbols                       -> search autocomplete
                     /api/upload (POST/DELETE)          -> attach/clear a document
                     /api/analyze, /api/resume          -> legacy desk
  tools.py         loads backend/.env (dotenv) + original mock tools/schemas.
  data/*.json      sample data + offline fallback.
```

## Analyst step-by-step HITL

```
you: stock + task ─▶ agent proposes step ─▶ [Approve / Redirect / Stop]
                            ▲                          │
                            └──── runs step, then ◀────┘  (until you finalise)
```
Endpoints: `/api/task/start?ticker=&task=&thread=` then
`/api/task/step?thread=&decision=approve|stop|redirect:<text>`.

## Chat agent tools

| Tool | What it does |
|---|---|
| get_quote | latest price + day change |
| get_price_chart | 6-month series, rendered as a chart in the UI |
| get_fundamentals | PE, market cap, margins, ROE |
| analyze_news_sentiment | pulls news, an LLM scores the mood (GenAI in a tool) |
| get_splits | historical stock splits / corporate actions |
| ask_document | answers from a PDF/Word doc the user uploaded to the chat (e.g. financial statements) |
| deep_desk_analysis | runs the multi-agent Desk and returns its verdict + action |

`get_quote` now returns the **live intraday price** (real-time spot via yfinance
`fast_info`/1-min bar), today's % move vs the previous close, and the market
state (REGULAR/CLOSED/PRE/POST) — not the last daily close.

## Run

```bash
cd backend
python -m venv .mumpy
.mumpy\Scripts\Activate.ps1            # Windows PowerShell
# (mac/linux: source .mumpy/bin/activate)
pip install -r requirements.txt -r requirements-langgraph.txt

# create backend/.env  (auto-loaded by tools.py):
#   GROQ_API_KEY=gsk_xxx
#   LANGCHAIN_API_KEY=ls__xxx          (optional, LangSmith)
#   LANGCHAIN_TRACING_V2=true
#   LANGCHAIN_PROJECT=mumpy-agent

uvicorn app_multi:app --reload --port 8000
```
Health: http://localhost:8000/api/health

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173
```

## Notes

- **NSE symbols**: type any, e.g. RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK, SBIN,
  TATAMOTORS, BHARTIARTL, ITC. market.py adds the ".NS" suffix for Yahoo.
- **Live vs Sample**: every chart shows a badge. LIVE = fresh yfinance data;
  SAMPLE = bundled offline data used when the live feed is unavailable. The nine
  seeded symbols above always work offline; others need a live fetch.
- **yfinance can be blocked / rate-limited**. If live fails, seeded symbols fall
  back to clearly-labelled sample data; unknown symbols return a clean "couldn't
  fetch" message instead of inventing numbers. curl_cffi is included because recent
  yfinance needs it. If live still fails, use a network that isn't blocking Yahoo,
  or rely on the seeded symbols for the talk.
- The side **Chat** shares the stock symbol with the **Analyst** (change it in
  either; the other follows) until you type a different one in the chat.
- **Not investment advice.** Teaching demo of agentic patterns.

## Speech + slides
See SPEECH.md (10-minute script) and MumPy_Talk.pptx (4 slides). MULTI_AGENT.md
has the Desk code walkthrough.