"""
chat_agent.py
-------------
Conversational ReAct agent over NSE stocks. Pick a stock, ask anything; the agent
chooses which tools to call. Ten tools, each grounded in market.py data.

Guardrails to keep answers good:
  - recursion_limit caps the loop so it can't spin forever
  - tools return terminal text when data is missing; the system prompt forbids retrying
  - the agent answers only from tool output, never invents numbers
"""

import json
import os

from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
from langchain_groq import ChatGroq
from langgraph.prebuilt import create_react_agent

import market
import docstore

# The active chat thread for the in-flight request. The document Q&A tool reads
# this to find the right uploaded document (a tool only receives the LLM's args,
# not the thread). The demo serves one chat stream at a time, so a module-level
# holder is sufficient; set at the top of run_chat().
_ACTIVE = {"thread": None}

# Groq-hosted model. Upgraded from llama-3.3-70b to the 120B gpt-oss for stronger
# reasoning and tool selection — still uses your existing GROQ_API_KEY (free/fast),
# confirmed available on this account. To revert/swap, change this one line
# (fallbacks: "llama-3.3-70b-versatile", "qwen/qwen3-32b").
MODEL = "openai/gpt-oss-120b"
_llm = ChatGroq(model=MODEL, temperature=0.3, api_key=os.environ.get("GROQ_API_KEY", ""))
_history: dict = {}


def _interpret(instruction: str, data) -> str:
    """LLM analysis grounded ONLY in the real numbers we pass it."""
    return _llm.invoke([HumanMessage(content=(
        "You are an equity analyst for Indian (NSE) stocks. Use ONLY the data below — "
        "never invent numbers, dates or facts. All money is in Indian Rupees (₹); never "
        "use '$'. Be concise, specific, and cite the actual figures.\n\n"
        f"DATA:\n{json.dumps(data, default=str)}\n\nTASK: {instruction}"
    ))]).content


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
@tool
def get_quote(ticker: str) -> str:
    """Latest LIVE price for an NSE stock: real-time/intraday spot price, today's %
    move vs the previous close, and the market state (REGULAR=open / CLOSED / PRE /
    POST) with an as_of timestamp. Use this for 'current price' / 'price right now'."""
    return json.dumps(market.quote(ticker), default=str)


@tool
def get_price_chart(ticker: str) -> str:
    """6-month price history. The chart is shown to the user automatically; just
    comment on the trend, don't list numbers."""
    b = market.bundle(ticker); p = b["price"]
    return json.dumps({"_chart": True, "ticker": b["ticker"], "change_pct": p["change_pct"],
                       "start": p["start"], "end": p["end"], "high": p["high"], "low": p["low"]}, default=str)


@tool
def get_fundamentals(ticker: str) -> str:
    """Valuation and financial-health metrics (PE, PB, market cap, margins, ROE)."""
    return json.dumps(market.fundamentals(ticker), default=str)


@tool
def get_valuation(ticker: str) -> str:
    """A compact valuation snapshot (PE, PB, market cap, dividend yield)."""
    return json.dumps(market.valuation(ticker), default=str)


@tool
def analyze_news_sentiment(ticker: str) -> str:
    """Pull recent news and judge overall sentiment (Positive / Negative / Mixed) with a reason."""
    items = market.news(ticker)
    if not items:
        return "No recent news available; cannot judge sentiment."
    heads = "\n".join(f"- {n['headline']}" for n in items if n.get("headline"))
    mood = _llm.invoke([HumanMessage(content=(
        f"Headlines for {ticker}:\n{heads}\n\nClassify overall sentiment as Positive, "
        "Negative or Mixed and give one sentence why. Start with the label."))]).content
    return f"{mood}\n\nHeadlines:\n{heads}"


@tool
def get_news_headlines(ticker: str) -> str:
    """Just the recent news headlines for an NSE stock (no analysis)."""
    items = market.news(ticker)
    return "\n".join(f"- {n['headline']}" for n in items if n.get("headline")) or "No recent news available."


@tool
def get_splits(ticker: str) -> str:
    """Historical stock splits / corporate actions."""
    s = market.splits(ticker)
    return json.dumps(s, default=str) if s else "No stock splits on record."


@tool
def get_dividends(ticker: str) -> str:
    """Dividend history (recent years) for an NSE stock."""
    d = market.dividends(ticker)
    return json.dumps(d, default=str) if d else "No dividend history on record."


@tool
def get_52week_range(ticker: str) -> str:
    """The 52-week high and low for an NSE stock."""
    return json.dumps(market.week52(ticker), default=str)


@tool
def get_performance(ticker: str) -> str:
    """Recent performance summary: period change %, high and low."""
    return json.dumps(market.performance(ticker), default=str)


@tool
def ask_document(question: str) -> str:
    """Answer a question using the user's UPLOADED document (e.g. an annual report,
    financial statement or any PDF/Word file they attached to this chat). Use this
    whenever the user refers to 'the document', 'the uploaded file', 'the report',
    'the financial statement', 'the PDF', or asks something that should come from
    their file rather than market data. Pass the user's full question."""
    thread = _ACTIVE.get("thread")
    if not thread or not docstore.has_document(thread):
        return "No document has been uploaded to this chat yet. Ask the user to upload a PDF or Word file first."
    context = docstore.retrieve(thread, question, k=6)
    if not context.strip():
        return "The uploaded document doesn't appear to contain anything relevant to that question."
    name = docstore.doc_name(thread)
    answer = _llm.invoke([HumanMessage(content=(
        "You are answering strictly from the user's uploaded document"
        f" ('{name}'). Use ONLY the excerpts below — never invent figures, dates or "
        "facts. If the answer isn't in the excerpts, say it isn't in the document. "
        "Quote the relevant numbers. If money is shown in rupees, keep ₹.\n\n"
        f"DOCUMENT EXCERPTS:\n{context}\n\nQUESTION: {question}"
    ))]).content
    return answer or "I couldn't extract an answer from the document for that question."


@tool
def deep_desk_analysis(ticker: str) -> str:
    """Run the multi-agent research desk (Researcher, Risk, Synthesiser) and return
    a BUY/HOLD/SELL verdict with a proposed action. Use for a thorough recommendation."""
    from agent_multi import researcher, risk_check, synthesize
    b = market.bundle(ticker)
    state = {"data": {"price": b["price"], "fundamentals": b["fundamentals"], "news": b["news"]}}
    state.update(researcher(state)); state.update(risk_check(state)); state.update(synthesize(state))
    return f"DESK VERDICT\n{state['recommendation']}\nProposed action: {state['action']}"


@tool
def get_fundamental_analysis(ticker: str) -> str:
    """Interpret the fundamentals into strengths, weaknesses and a business-quality verdict
    (not just raw numbers). Use for 'fundamental analysis' / 'is this a good company'."""
    f = market.fundamentals(ticker)
    if not f:
        return "Fundamentals not available for this stock."
    return _interpret("Assess financial health and valuation: key strengths and weaknesses "
                      "across PE, PB, ROE, margins, debt/equity and yield, then a one-line "
                      "quality verdict.", f)


@tool
def get_technical_analysis(ticker: str) -> str:
    """Read the price trend and momentum versus moving averages and the 6-month / 52-week
    range. Use for 'technical analysis' / 'how's the chart looking'."""
    b = market.bundle(ticker)
    closes = [p["close"] for p in b["chart"]
              if isinstance(p.get("close"), (int, float)) and p["close"] == p["close"]]
    if len(closes) < 5:
        return "Not enough price history for a technical read."
    sma = lambda n: round(sum(closes[-n:]) / min(n, len(closes)), 2)
    data = {"last": closes[-1], "sma20": sma(20), "sma50": sma(50), "high_6m": max(closes),
            "low_6m": min(closes), "week52": b.get("week52", {}), "change_6m_pct": b["price"]["change_pct"]}
    return _interpret("Short technical read: trend, momentum, position vs 20/50-day averages "
                      "and the 6-month / 52-week range. Do not predict prices.", data)


@tool
def explain_price_move(ticker: str) -> str:
    """Explain the likely reason for the recent rise or downfall, linking price action to news.
    Use for 'why did it fall/rise', 'reason for downfall'."""
    b = market.bundle(ticker)
    p = b["price"]
    direction = "rise" if (p.get("change_pct") or 0) >= 0 else "decline"
    data = {"change_6m_pct": p["change_pct"], "start": p["start"], "end": p["end"],
            "high": p["high"], "low": p["low"],
            "news": [n.get("headline") for n in b["news"] if n.get("headline")]}
    return _interpret(f"Explain the likely reasons for the recent {direction} "
                      f"({p['change_pct']}% over 6 months), tying the move to the news. "
                      "State clearly this is interpretation, not certainty.", data)


@tool
def get_risk_assessment(ticker: str) -> str:
    """List the key downside risks right now (valuation, leverage, growth, news, momentum)."""
    b = market.bundle(ticker)
    data = {"fundamentals": b["fundamentals"], "valuation": market.valuation(ticker),
            "change_6m_pct": b["price"]["change_pct"], "week52": b["week52"],
            "news": [n.get("headline") for n in b["news"] if n.get("headline")]}
    return _interpret("List the key downside risks as 3-5 short bullets, each tied to the data.", data)


@tool
def get_bull_bear_case(ticker: str) -> str:
    """Lay out the bull case versus the bear case, then say which looks stronger."""
    b = market.bundle(ticker)
    data = {"fundamentals": b["fundamentals"], "price": b["price"], "week52": b["week52"],
            "analyst": b.get("analyst", {}),
            "news": [n.get("headline") for n in b["news"] if n.get("headline")]}
    return _interpret("Give a balanced BULL case and BEAR case (2-3 grounded points each), "
                      "then which is stronger and why.", data)


@tool
def get_analyst_ratings(ticker: str) -> str:
    """Brokerage price targets and buy/hold/sell consensus (live-only data)."""
    a = market.analyst_ratings(ticker)
    return json.dumps(a, default=str) if a else "Analyst targets/consensus aren't available for this stock (live-only)."


@tool
def get_quarterly_results(ticker: str) -> str:
    """Recent quarterly revenue and net profit, in rupees crore (live-only data)."""
    q = market.quarterly(ticker)
    return json.dumps(q, default=str) if q else "Quarterly results aren't available for this stock (live-only)."


@tool
def get_key_stats(ticker: str) -> str:
    """Extended stats: beta, 50/200-day averages, revenue/earnings growth, margins (live-only)."""
    s = market.stats(ticker)
    return json.dumps(s, default=str) if s else "Extended stats aren't available for this stock (live-only)."


TOOLS = [get_quote, get_price_chart, get_fundamentals, get_valuation, get_fundamental_analysis,
         get_technical_analysis, explain_price_move, get_risk_assessment, get_bull_bear_case,
         analyze_news_sentiment, get_news_headlines, get_splits, get_dividends, get_52week_range,
         get_performance, get_analyst_ratings, get_quarterly_results, get_key_stats,
         ask_document, deep_desk_analysis]

SYSTEM = SystemMessage(content=(
    "You are a careful equity research assistant for Indian (NSE) stocks. "
    "RULES: Only state facts returned by a tool; never invent prices, numbers, "
    "dates or news. Call each tool AT MOST ONCE per question; if a tool returns "
    "no data or an error, do NOT call it again, just tell the user and finish. "
    "Pick the few tools that actually answer the question; don't call everything. "
    "Charts render automatically, so just comment on the trend. Be concise. Add "
    "'Informational only, not investment advice.' only when giving a recommendation."
))

AGENT = create_react_agent(_llm, TOOLS, prompt=SYSTEM)


def _short(t, n=220):
    t = str(t); return t if len(t) <= n else t[:n] + "…"


async def run_chat(ticker: str, question: str, thread_id: str):
    _ACTIVE["thread"] = thread_id           # so ask_document finds this chat's upload
    history = _history.get(thread_id, [])
    doc_note = ""
    if docstore.has_document(thread_id):
        doc_note = (f"\n[A document is attached to this chat: '{docstore.doc_name(thread_id)}'. "
                    "If the question is about its contents, use the ask_document tool.]")
    user_msg = HumanMessage(content=f"[Stock in focus: {ticker.upper()} (NSE)]{doc_note}\n{question}")
    messages = history + [user_msg]
    final_answer = ""
    try:
        async for update in AGENT.astream({"messages": messages},
                                          config={"recursion_limit": 20}, stream_mode="updates"):
            for node, payload in update.items():
                for msg in payload.get("messages", []):
                    if isinstance(msg, AIMessage):
                        for tc in (msg.tool_calls or []):
                            yield {"type": "tool_call", "name": tc["name"], "args": tc["args"]}
                        if not msg.tool_calls and msg.content:
                            final_answer = msg.content
                            yield {"type": "answer", "text": msg.content}
                    elif isinstance(msg, ToolMessage):
                        if msg.name == "get_price_chart":
                            try:
                                meta = json.loads(msg.content); b = market.bundle(meta["ticker"])
                                yield {"type": "chart", "ticker": meta["ticker"], "series": b["chart"],
                                       "change_pct": meta.get("change_pct"), "source": b.get("source", "sample")}
                            except Exception:
                                pass
                        else:
                            yield {"type": "tool_result", "name": msg.name, "text": _short(msg.content)}
    except Exception as e:
        msg = str(e)
        if "recursion" in msg.lower():
            yield {"type": "answer", "text": "I couldn't fully resolve that in a few steps. Try asking something more specific (e.g. 'news sentiment for this stock')."}
        else:
            yield {"type": "error", "text": msg}
        return

    _history[thread_id] = (messages + [AIMessage(content=final_answer)])[-8:]