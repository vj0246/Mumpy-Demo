"""
agent_task.py
-------------
A task-driven analyst agent with STEP-BY-STEP human-in-the-loop.

You give it a stock + a task. Then, for every move:

    agent proposes ONE next step  ->  you Approve / Redirect / Stop  ->  it runs it
                                          ↑                                  │
                                          └──────────── repeat ◄─────────────┘
                                                  until you finalise

Nothing happens without your approval. The agent only ever proposes the *next*
step; you stay in control the whole way. Answers are grounded in fetched data,
not invented — if data can't be fetched, it says so and keeps going.

No interrupt() magic: each step is a plain LLM "what next" call, gated by an
HTTP round-trip. Session state lives in _sessions keyed by thread id.
"""

import json
import os

from langchain_core.messages import HumanMessage
from langchain_groq import ChatGroq

import market

# Groq-hosted model. Upgraded from llama-3.3-70b to the 120B gpt-oss for stronger
# reasoning and tighter tool-step planning — still uses your existing GROQ_API_KEY
# (free/fast), confirmed available on this account. To revert/swap, change this one
# line (fallbacks: "llama-3.3-70b-versatile", "qwen/qwen3-32b").
MODEL = "openai/gpt-oss-120b"
_llm = ChatGroq(model=MODEL, temperature=0.3, api_key=os.environ.get("GROQ_API_KEY", ""))

_sessions: dict = {}   # thread_id -> session dict

# Tools the agent may propose. Keep names human-readable for the approval card.
# Raw-data tools fetch numbers; analysis tools interpret them (grounded, never invented).
TOOLS = {
    # quick facts
    "quote": "Get the latest share price (and the recent % move)",
    "fifty_two_week": "Get the 52-week high and low",
    "performance": "Summarise recent performance (change %, high, low)",
    "price_trend": "Look at the 6-month price trend (shows a chart)",
    # fundamentals & financials
    "fundamentals": "Pull raw valuation / financial-health metrics",
    "valuation": "A compact valuation snapshot (PE, PB, market cap, yield)",
    "fundamental_analysis": "Interpret the fundamentals: strengths, weaknesses, quality verdict",
    "quarterly_results": "Recent quarterly revenue, net profit, operating income & EPS",
    "balance_sheet": "Balance sheet: shareholders' equity, assets, liabilities, debt, cash",
    "key_stats": "Extended stats: beta, 50/200-day averages, growth, margins",
    "dividends": "Review the dividend history",
    "dividend_analysis": "Assess dividend quality: yield, growth, consistency",
    "stock_splits": "Review historical stock splits / corporate actions",
    # price / technicals
    "technical_analysis": "Read the trend & momentum vs moving averages and ranges (shows a chart)",
    "explain_move": "Explain the likely reason for the recent rise / downfall",
    # news & sentiment
    "news_sentiment": "Pull recent news and judge the market sentiment",
    "news_headlines": "List the recent news headlines (no analysis)",
    "news_summary": "Summarise what the recent news means for the stock",
    # research views
    "analyst_ratings": "Brokerage price targets and buy/hold/sell consensus",
    "risk_assessment": "List the key downside risks right now",
    "bull_bear_case": "Lay out the bull case vs the bear case",
    "verdict": "A grounded BUY / HOLD / SELL stance with reasons",
    # terminate
    "finish": "Stop gathering and write the final report for the task",
}

MAX_STEPS = 6   # hard cap so the approval loop ALWAYS terminates


def _llm_json(prompt: str) -> dict:
    raw = _llm.invoke([HumanMessage(content=prompt)]).content
    try:
        return json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    except Exception:
        return {}


# --------------------------------------------------------------------------- #
# Propose the next step
# --------------------------------------------------------------------------- #
def _propose(sess: dict, redirect: str = "") -> dict:
    done_tools = [c["tool"] for c in sess["context"]]

    # Hard cap: once enough steps are gathered, always wrap up (loop can't run forever).
    if not redirect and len(done_tools) >= MAX_STEPS:
        return {"tool": "finish",
                "summary": "I've gathered enough across several steps — approve to get the final report."}

    tool_list = "\n".join(f"- {k}: {v}" for k, v in TOOLS.items() if k != "finish")
    ctx = "\n\n".join(f"[{c['tool']}] {c['result']}" for c in sess["context"]) or "nothing yet"
    extra = f"\nThe user redirected you: '{redirect}'. Honour it." if redirect else ""
    prompt = (
        f"You are an equity analyst agent working on this TASK for {sess['ticker']} (NSE):\n"
        f"\"{sess['task']}\"\n\n"
        f"Tools available:\n{tool_list}\n\n"
        f"Steps already done: {done_tools or 'none'}\n"
        f"Findings so far:\n{ctx}\n{extra}\n\n"
        "FIRST decide: do the findings so far ALREADY answer the task?\n"
        "- A simple/factual question is fully answered by ONE matching tool — once that "
        "tool has run, set done=true. (price->quote, 52-week->fifty_two_week, "
        "valuation/'is it cheap'->valuation or fundamental_analysis, dividends->dividends, "
        "splits->stock_splits, 'why did it move/fall'->explain_move, results->quarterly_results.)\n"
        "- Only keep going (done=false) for broad tasks that genuinely need several angles "
        "(full analysis, risk review, a buy/hold/sell verdict).\n"
        "If done=false, pick the SINGLE most useful NEXT tool — never one already done.\n"
        'Reply ONLY as JSON: {"done": true or false, "tool": "<tool name>", '
        '"summary": "one short sentence on what you will do and why"}'
    )
    obj = _llm_json(prompt)

    # Explicit completion signal -> finish.
    if obj.get("done") is True:
        return {"tool": "finish",
                "summary": obj.get("summary", "I have enough to answer — approve to get the report.")}

    tool = obj.get("tool", "finish")
    if tool not in TOOLS:
        tool = "finish"
    # Repeat-guard: re-proposing a finished tool (without a redirect) means it's spinning.
    if tool != "finish" and tool in done_tools and not redirect:
        return {"tool": "finish",
                "summary": "I've already covered that — approve to get the final report."}
    return {"tool": tool, "summary": obj.get("summary", "Proceed to the next step.")}


# --------------------------------------------------------------------------- #
# Execute one approved step (grounded in real data)
# --------------------------------------------------------------------------- #
def _interpret(instruction: str, data) -> str:
    """LLM analysis grounded ONLY in the real numbers we pass it."""
    return _llm.invoke([HumanMessage(content=(
        "You are an equity analyst for Indian (NSE) stocks. Use ONLY the data below — "
        "never invent numbers, dates or facts. All money is in Indian Rupees (₹); never "
        "use '$'. Be concise, specific, and cite the actual figures.\n\n"
        f"DATA:\n{json.dumps(data, default=str)}\n\nTASK: {instruction}"
    ))]).content


def _chart_payload(b: dict) -> dict:
    return {"ticker": b["ticker"], "series": b["chart"],
            "change_pct": b["price"]["change_pct"], "source": b.get("source", "sample")}


# --- readable formatting: turn metric dicts / quarter lists into markdown tables ---
_LABELS = {
    "pe": "P/E", "pb": "P/B", "market_cap_cr": "Market cap", "market_cap": "Market cap",
    "roe_pct": "ROE", "net_margin_pct": "Net margin", "operating_margin_pct": "Operating margin",
    "gross_margin_pct": "Gross margin", "debt_to_equity": "Debt / equity",
    "dividend_yield_pct": "Dividend yield", "eps_ttm": "EPS (TTM)", "revenue_ttm_cr": "Revenue (TTM)",
    "shareholders_equity_cr": "Shareholders' equity", "total_assets_cr": "Total assets",
    "total_liabilities_cr": "Total liabilities", "total_debt_cr": "Total debt", "cash_cr": "Cash",
    "retained_earnings_cr": "Retained earnings", "working_capital_cr": "Working capital",
    "book_value_per_share": "Book value / share", "as_of": "As of", "beta": "Beta",
    "ma50": "50-day avg", "ma200": "200-day avg", "revenue_growth_pct": "Revenue growth (YoY)",
    "earnings_growth_pct": "Earnings growth (YoY)", "current_ratio": "Current ratio",
    "high": "High", "low": "Low", "period_change_pct": "Period change", "last_close": "Last close",
}


def _fmt_val(k, v):
    if not isinstance(v, (int, float)):
        return str(v)
    if k.endswith("_cr"):
        return f"₹{v:,.0f} cr"
    if k == "market_cap":
        return f"₹{v:,.0f}"
    if k.endswith("_pct"):
        return f"{v:,.2f}%"
    if k in ("ma50", "ma200", "eps_ttm", "book_value_per_share", "last_close", "high", "low"):
        return f"₹{v:,.2f}"
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def _md_metrics(d: dict) -> str:
    if not d:
        return "_No data available._"
    rows = "\n".join(f"| {_LABELS.get(k, k.replace('_', ' '))} | {_fmt_val(k, v)} |" for k, v in d.items())
    return f"| Metric | Value |\n|---|---|\n{rows}"


def _c(v):
    return f"{v:,.0f}" if isinstance(v, (int, float)) else "—"


def _md_quarters(rows: list) -> str:
    if not rows:
        return "_No quarterly data available._"
    head = ("| Quarter | Revenue (₹ cr) | Net profit (₹ cr) | Op. income (₹ cr) | EPS (₹) |\n"
            "|---|--:|--:|--:|--:|")
    body = "\n".join(
        f"| {r.get('quarter','')} | {_c(r.get('revenue_cr'))} | {_c(r.get('net_income_cr'))} "
        f"| {_c(r.get('operating_income_cr'))} | {r.get('eps') if r.get('eps') is not None else '—'} |"
        for r in rows)
    return head + "\n" + body


def _execute(tool: str, ticker: str):
    """Returns (result_text, chart_payload_or_None). Never invents data."""
    try:
        if tool == "quote":
            q = market.quote(ticker)
            chg = q.get("change_pct")
            chg_txt = f"{chg:+.2f}% today" if chg is not None else "change n/a"
            state = q.get("market_state")
            STATE = {"REGULAR": "market open", "CLOSED": "market closed",
                     "PRE": "pre-market", "POST": "post-market"}
            live = q.get("source") == "live"
            tag = (f" [{STATE.get(state, state)}]" if state else "") if live else ""
            asof = f" as of {q['as_of']}" if q.get("as_of") else ""
            return (f"Latest price: ₹{q['price']} ({chg_txt}){tag}. "
                    f"Source: {q.get('source', 'sample')} data{asof}."), None

        if tool == "fundamental_analysis":
            f = market.fundamentals(ticker)
            if not f:
                return "Fundamentals not available for this stock.", None
            return _interpret(
                "Assess financial health and valuation. Call out the key strengths and "
                "weaknesses across PE, PB, ROE, margins, debt/equity and dividend yield, "
                "then give a one-line verdict on business quality.", f), None

        if tool == "technical_analysis":
            b = market.bundle(ticker)
            closes = [p["close"] for p in b["chart"]
                      if isinstance(p.get("close"), (int, float)) and p["close"] == p["close"]]
            if len(closes) < 5:
                return "Not enough price history for a technical read.", None
            sma = lambda n: round(sum(closes[-n:]) / min(n, len(closes)), 2)
            data = {"last": closes[-1], "sma20": sma(20), "sma50": sma(50),
                    "high_6m": max(closes), "low_6m": min(closes),
                    "week52": b.get("week52", {}), "change_6m_pct": b["price"]["change_pct"]}
            return _interpret(
                "Give a short technical read: trend (up / down / sideways), momentum, and "
                "where price sits versus its 20- and 50-day averages and its 6-month / "
                "52-week range. Do NOT predict future prices.", data), _chart_payload(b)

        if tool == "explain_move":
            b = market.bundle(ticker)
            p = b["price"]
            direction = "rise" if (p.get("change_pct") or 0) >= 0 else "decline"
            data = {"change_6m_pct": p["change_pct"], "start": p["start"], "end": p["end"],
                    "high": p["high"], "low": p["low"],
                    "news": [n.get("headline") for n in b["news"] if n.get("headline")]}
            return _interpret(
                f"Explain the most likely reasons behind the recent {direction} "
                f"({p['change_pct']}% over 6 months), connecting the price move to the news. "
                "Be explicit that this is interpretation, not certainty.", data), _chart_payload(b)

        if tool == "risk_assessment":
            b = market.bundle(ticker)
            data = {"fundamentals": b["fundamentals"], "valuation": market.valuation(ticker),
                    "change_6m_pct": b["price"]["change_pct"], "week52": b["week52"],
                    "news": [n.get("headline") for n in b["news"] if n.get("headline")]}
            return _interpret(
                "List the key DOWNSIDE risks for this stock right now (valuation, leverage, "
                "growth, news, momentum) as 3-5 short bullet points, each tied to the data.", data), None

        if tool == "bull_bear_case":
            b = market.bundle(ticker)
            data = {"fundamentals": b["fundamentals"], "price": b["price"],
                    "week52": b["week52"], "analyst": b.get("analyst", {}),
                    "news": [n.get("headline") for n in b["news"] if n.get("headline")]}
            return _interpret(
                "Give a balanced BULL case and BEAR case (2-3 grounded points each), then say "
                "which looks stronger and why.", data), None

        if tool == "verdict":
            b = market.bundle(ticker)
            data = {"fundamentals": b["fundamentals"], "valuation": market.valuation(ticker),
                    "price": b["price"], "week52": b["week52"], "analyst": b.get("analyst", {}),
                    "news": [n.get("headline") for n in b["news"] if n.get("headline")]}
            return _interpret(
                "Give a clear BUY / HOLD / SELL stance with 2-3 supporting reasons grounded in "
                "the data, plus the single biggest risk. End with: 'Informational only, not "
                "investment advice.'", data), None

        if tool == "dividend_analysis":
            d = market.dividends(ticker)
            if not d:
                return "No dividend history on record.", None
            data = {"dividends": d, "dividend_yield_pct": market.fundamentals(ticker).get("dividend_yield_pct")}
            return _interpret(
                "Assess the dividend: is the payout growing, how consistent is it, and is the "
                "yield attractive? Keep it to a few sentences.", data), None

        if tool == "news_summary":
            heads = [n["headline"] for n in market.news(ticker) if n.get("headline")]
            if not heads:
                return "No recent news available.", None
            return "Summary:\n" + _interpret(
                "Summarise in 3-4 sentences what these headlines collectively mean for the "
                "stock and its near-term outlook.", {"headlines": heads}), None

        if tool == "analyst_ratings":
            a = market.analyst_ratings(ticker)
            if not a:
                return "Analyst price targets / consensus aren't available for this stock (live-only data).", None
            return "**Analyst consensus**\n\n" + _md_metrics(a), None

        if tool == "quarterly_results":
            q = market.quarterly(ticker)
            if not q:
                return "Quarterly results aren't available for this stock (live-only data).", None
            return "**Recent quarterly results**\n\n" + _md_quarters(q), None

        if tool == "balance_sheet":
            bs = market.balance_sheet(ticker)
            if not bs:
                return "Balance-sheet data isn't available for this stock (live-only data).", None
            return "**Balance sheet**\n\n" + _md_metrics(bs), None

        if tool == "key_stats":
            s = market.stats(ticker)
            if not s:
                return "Extended stats (beta, moving averages, growth) aren't available for this stock (live-only data).", None
            return "**Key stats**\n\n" + _md_metrics(s), None

        if tool == "news_sentiment":
            items = market.news(ticker)
            if not items:
                return "No recent news available for this stock.", None
            heads = "\n".join(f"- {n['headline']}" for n in items if n.get("headline"))
            mood = _llm.invoke([HumanMessage(content=(
                f"Headlines for {ticker}:\n{heads}\n\nClassify overall sentiment as "
                "Positive, Negative or Mixed and give one sentence why. Start with the label."
            ))]).content
            return f"{mood}\n\nHeadlines:\n{heads}", None

        if tool == "news_headlines":
            items = market.news(ticker)
            heads = "\n".join(f"- {n['headline']}" for n in items if n.get("headline"))
            return ("Recent headlines:\n" + heads) if heads else "No recent news available.", None

        if tool == "fundamentals":
            f = market.fundamentals(ticker)
            return ("**Fundamentals**\n\n" + _md_metrics(f)) if f else "Fundamentals aren't available for this stock.", None

        if tool == "valuation":
            v = market.valuation(ticker)
            return ("**Valuation**\n\n" + _md_metrics(v)) if v else "Valuation metrics aren't available for this stock.", None

        if tool == "performance":
            return "**Performance**\n\n" + _md_metrics(market.performance(ticker)), None

        if tool == "fifty_two_week":
            return "**52-week range**\n\n" + _md_metrics(market.week52(ticker)), None

        if tool == "dividends":
            d = market.dividends(ticker)
            if not d:
                return "No dividend history on record.", None
            body = "\n".join(f"| {x.get('year','')} | ₹{x.get('amount')} |" for x in d)
            return "**Dividend history**\n\n| Year | Dividend / share |\n|---|--:|\n" + body, None

        if tool == "price_trend":
            b = market.bundle(ticker)
            p = b["price"]
            txt = (f"6-month move: {p['change_pct']}% (from {p['start']} to {p['end']}, "
                   f"high {p['high']}, low {p['low']}).")
            chart = {"ticker": b["ticker"], "series": b["chart"], "change_pct": p["change_pct"],
                     "source": b.get("source", "sample")}
            return txt, chart

        if tool == "stock_splits":
            s = market.splits(ticker)
            if not s:
                return "No stock splits on record.", None
            body = "\n".join(f"| {x.get('date','')} | {x.get('ratio')}:1 |" for x in s)
            return "**Stock splits**\n\n| Date | Ratio |\n|---|---|\n" + body, None

    except Exception as e:
        return f"Could not fetch live data for this step ({e}). Continuing with what we have.", None

    return "Nothing to execute.", None


def _report(sess: dict) -> str:
    ctx = "\n\n".join(f"[{c['tool']}] {c['result']}" for c in sess["context"]) or "no data gathered"
    out = _llm.invoke([HumanMessage(content=(
        f"Task: {sess['task']}\nStock: {sess['ticker']} (NSE)\n\n"
        f"Everything gathered:\n{ctx}\n\n"
        "Directly ANSWER the task using ONLY the findings above; do not invent numbers. "
        "If it was a simple factual question, answer in 1-2 sentences — do not pad it. "
        "If it was a broad analysis, give a short structured summary with a clear takeaway. "
        "If some data was missing, say so briefly. End with one line: "
        "'Informational only, not investment advice.'"
    ))]).content
    return out


# --------------------------------------------------------------------------- #
# Public streaming API
# --------------------------------------------------------------------------- #
async def start_task(ticker: str, task: str, thread_id: str):
    tk = ticker.upper()
    # preflight: make sure we can get data at all before proposing steps
    try:
        b = market.bundle(tk)
        source = b.get("source", "sample")
    except Exception as e:
        yield {"type": "final", "text": f"Couldn't start: {e}"}
        return

    sess = {"ticker": tk, "task": task, "context": [], "pending": None, "source": source}
    _sessions[thread_id] = sess
    src_note = "live market data" if source == "live" else "sample data (live feed unavailable)"
    yield {"type": "intro", "text": f"Working on: \"{task}\" for {tk}. Using {src_note}. I'll propose each step for your approval."}
    prop = _propose(sess)
    sess["pending"] = prop
    yield {"type": "propose", "tool": prop["tool"], "summary": prop["summary"], "thread_id": thread_id}


async def step_task(thread_id: str, decision: str):
    sess = _sessions.get(thread_id)
    if not sess:
        yield {"type": "error", "text": "Session expired. Start a new task."}
        return

    # Redirect: re-propose honouring the user's instruction
    if decision.startswith("redirect:"):
        prop = _propose(sess, redirect=decision[len("redirect:"):].strip())
        sess["pending"] = prop
        yield {"type": "propose", "tool": prop["tool"], "summary": prop["summary"], "thread_id": thread_id}
        return

    # Stop: finalise now
    if decision == "stop":
        yield {"type": "final", "text": _report(sess)}
        _sessions.pop(thread_id, None)
        return

    # Approve the pending step
    prop = sess["pending"]
    if not prop or prop["tool"] == "finish":
        yield {"type": "final", "text": _report(sess)}
        _sessions.pop(thread_id, None)
        return

    result, chart = _execute(prop["tool"], sess["ticker"])
    sess["context"].append({"tool": prop["tool"], "result": result})
    if chart:
        yield {"type": "chart", **chart}
    yield {"type": "step_result", "tool": prop["tool"], "text": result}

    # Propose the next step
    nxt = _propose(sess)
    sess["pending"] = nxt
    if nxt["tool"] == "finish":
        yield {"type": "propose", "tool": "finish",
               "summary": nxt.get("summary", "I have enough to answer. Approve to get the final report."),
               "thread_id": thread_id}
    else:
        yield {"type": "propose", "tool": nxt["tool"], "summary": nxt["summary"], "thread_id": thread_id}