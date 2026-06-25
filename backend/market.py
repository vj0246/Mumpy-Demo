"""
market.py
---------
NSE market data. Tries live yfinance first, then falls back to embedded SAMPLE
data (seed_data.py) so the demo ALWAYS works, even with no network or a blocked
Yahoo endpoint. Every bundle carries a 'source' field ("live" or "sample") that
the UI shows as a badge, so sample data is never mistaken for live.
"""

import time
from seed_data import SEEDS

_CACHE: dict = {}
_TTL = 300
# The full bundle (chart, fundamentals, news) is fine cached for 5 min, but the
# live PRICE must refresh far more often or it shows yesterday's close while the
# market is open. So the spot quote gets its own short-lived cache.
_QUOTE_CACHE: dict = {}
_QUOTE_TTL = 20
_SEED = set(SEEDS)


def _nse(symbol: str) -> str:
    s = symbol.strip().upper()
    return s if (s.endswith(".NS") or s.endswith(".BO")) else s + ".NS"


def _base(symbol: str) -> str:
    return symbol.strip().upper().replace(".NS", "").replace(".BO", "")


def _ticker(symbol: str):
    """A yfinance Ticker on a browser-impersonating session when available.

    curl_cffi makes us look like a real Chrome client, which sharply reduces
    Yahoo's rate-limiting (the empty-body "possibly delisted" responses). If
    curl_cffi isn't installed we silently fall back to yfinance's default.
    """
    import yfinance as yf
    try:
        from curl_cffi import requests as _creq
        return yf.Ticker(_nse(symbol), session=_creq.Session(impersonate="chrome"))
    except Exception:
        return yf.Ticker(_nse(symbol))


def _history(tk, **kw):
    """tk.history with a few retries — Yahoo throttling is usually transient, so a
    short backoff turns most "no data" misfires into a real result."""
    last_exc = None
    for attempt in range(3):
        try:
            h = tk.history(**kw)
            if h is not None and not h.empty:
                return h
        except Exception as e:
            last_exc = e
        time.sleep(0.5 * (attempt + 1))
    if last_exc:
        raise last_exc
    raise ValueError("no history")


# --------------------------------------------------------------------------- #
# Sample bundle from embedded data
# --------------------------------------------------------------------------- #
def _sample_bundle(symbol: str) -> dict:
    d = SEEDS[_base(symbol)]
    closes = d["price_history"]["last_10_closes"]
    series = [{"i": i, "close": c} for i, c in enumerate(closes)]
    return {
        "ticker": _base(symbol), "name": d["name"], "source": "sample",
        "quote": {"price": d["price_history"]["end"], "change_pct": d["price_history"]["change_pct"]},
        "price": d["price_history"], "week52": d["week52"],
        "fundamentals": d["fundamentals"], "news": d["news"],
        "splits": d["splits"], "dividends": d["dividends"], "chart": series,
        "analyst": {}, "stats": {},   # analyst targets / extended stats are live-only
    }


# --------------------------------------------------------------------------- #
# Live bundle from yfinance
# --------------------------------------------------------------------------- #
def _live_bundle(symbol: str) -> dict:
    tk = _ticker(symbol)
    hist = _history(tk, period="6mo")
    if hist.empty:
        raise ValueError("no history")
    # yfinance often returns holiday / partial / not-yet-settled rows whose Close is
    # NaN. Drop them up front so NaN can never leak into the chart, the latest price,
    # or the % change. (This was the bug behind "last_close": NaN and "nan%" moves.)
    hist = hist.dropna(subset=["Close"])
    if hist.empty:
        raise ValueError("no valid closes")
    chart = [{"i": i, "date": str(idx.date()), "close": round(float(r["Close"]), 2)}
             for i, (idx, r) in enumerate(hist.iterrows())]
    closes = [c["close"] for c in chart]
    if len(closes) < 2:
        raise ValueError("not enough closes")
    change = round((closes[-1] / closes[0] - 1) * 100, 2)

    info = {}
    try:
        info = tk.info or {}
    except Exception:
        pass
    def _pct(v):  # yfinance gives margins/ROE as fractions (0.247); show as % (24.7)
        return round(v * 100, 2) if isinstance(v, (int, float)) else None

    mc = info.get("marketCap")
    fundamentals = {"pe": info.get("trailingPE"), "pb": info.get("priceToBook"),
                    "market_cap": mc, "market_cap_cr": round(mc / 1e7) if mc else None,
                    "net_margin_pct": _pct(info.get("profitMargins")),
                    "roe_pct": _pct(info.get("returnOnEquity")),
                    "dividend_yield_pct": info.get("dividendYield"),
                    "debt_to_equity": info.get("debtToEquity")}

    news = []
    try:
        for n in (tk.news or [])[:6]:
            c = n.get("content", n)
            news.append({"headline": c.get("title") or n.get("title", ""), "sentiment": "n/a"})
    except Exception:
        pass

    splits, dividends = [], []
    try:
        splits = [{"date": str(i.date()), "ratio": float(r)} for i, r in tk.splits.items()][-8:]
    except Exception:
        pass
    try:
        dvs = tk.dividends
        dividends = [{"year": i.year, "amount": round(float(v), 2)} for i, v in dvs.items()][-6:]
    except Exception:
        pass

    analyst = {"target_mean": info.get("targetMeanPrice"), "target_high": info.get("targetHighPrice"),
               "target_low": info.get("targetLowPrice"), "recommendation": info.get("recommendationKey"),
               "num_analysts": info.get("numberOfAnalystOpinions"), "current_price": closes[-1]}
    analyst = {k: v for k, v in analyst.items() if v is not None}
    stats = {"beta": info.get("beta"), "ma50": info.get("fiftyDayAverage"),
             "ma200": info.get("twoHundredDayAverage"), "revenue_growth_pct": _pct(info.get("revenueGrowth")),
             "earnings_growth_pct": _pct(info.get("earningsGrowth")), "gross_margin_pct": _pct(info.get("grossMargins")),
             "operating_margin_pct": _pct(info.get("operatingMargins")), "current_ratio": info.get("currentRatio")}
    stats = {k: v for k, v in stats.items() if v is not None}

    return {
        "ticker": _base(symbol), "name": info.get("shortName") or _base(symbol), "source": "live",
        "quote": {"price": closes[-1], "change_pct": change},
        "price": {"period": "6mo", "start": closes[0], "end": closes[-1],
                  "high": max(closes), "low": min(closes), "change_pct": change,
                  "avg_volume_m": round((info.get("averageVolume") or 0) / 1e6, 2)},
        "week52": {"high": info.get("fiftyTwoWeekHigh"), "low": info.get("fiftyTwoWeekLow")},
        "fundamentals": fundamentals, "news": news,
        "splits": splits, "dividends": dividends, "chart": chart,
        "analyst": analyst, "stats": stats,
    }


# --------------------------------------------------------------------------- #
# Live spot quote (the real-time price, refreshed every ~20s)
# --------------------------------------------------------------------------- #
def _num(v):
    """Return v as a float only if it's a real, finite number (NaN != NaN)."""
    return float(v) if isinstance(v, (int, float)) and v == v else None


def _live_quote(symbol: str) -> dict:
    """The current/intraday price — NOT the last daily close.

    yfinance's `history()` only returns settled daily bars, so during market
    hours `closes[-1]` is yesterday's (or this morning's) close. We instead read
    the live price from, in order of freshness: fast_info -> a 1-minute intraday
    bar -> .info. Day change is measured against the *previous close*, which is
    what an investor means by "today's move".
    """
    tk = _ticker(symbol)

    price = prev = day_high = day_low = state = None

    # 1) fast_info: the lightest, freshest endpoint (no full .info download).
    try:
        fi = tk.fast_info
        price = _num(getattr(fi, "last_price", None))
        prev = _num(getattr(fi, "previous_close", None))
        day_high = _num(getattr(fi, "day_high", None))
        day_low = _num(getattr(fi, "day_low", None))
    except Exception:
        pass

    # 2) A 1-minute intraday bar pins down the live price if fast_info missed it.
    if price is None:
        try:
            intr = tk.history(period="1d", interval="1m")
            intr = intr.dropna(subset=["Close"])
            if not intr.empty:
                price = _num(intr["Close"].iloc[-1])
                day_high = day_high or _num(intr["High"].max())
                day_low = day_low or _num(intr["Low"].min())
        except Exception:
            pass

    # 3) .info as a last resort (and for the market_state flag).
    if price is None or prev is None or state is None:
        info = {}
        try:
            info = tk.info or {}
        except Exception:
            info = {}
        price = price or _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice"))
        prev = prev or _num(info.get("regularMarketPreviousClose")) or _num(info.get("previousClose"))
        state = info.get("marketState")

    if price is None:
        raise ValueError("no live price")

    change_pct = round((price / prev - 1) * 100, 2) if prev else None
    return {
        "price": round(price, 2),
        "change_pct": change_pct,
        "prev_close": round(prev, 2) if prev else None,
        "day_high": round(day_high, 2) if day_high else None,
        "day_low": round(day_low, 2) if day_low else None,
        "market_state": state,        # REGULAR (open) / CLOSED / PRE / POST / None
        "as_of": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "live",
    }


def _cached_live_quote(symbol: str) -> dict:
    key = _base(symbol)
    now = time.time()
    if key in _QUOTE_CACHE and now - _QUOTE_CACHE[key][0] < _QUOTE_TTL:
        return _QUOTE_CACHE[key][1]
    q = _live_quote(symbol)
    _QUOTE_CACHE[key] = (now, q)
    return q


# --------------------------------------------------------------------------- #
# Public: cached bundle (live first, sample fallback)
# --------------------------------------------------------------------------- #
def bundle(symbol: str) -> dict:
    key = _base(symbol)
    now = time.time()
    if key in _CACHE and now - _CACHE[key][0] < _TTL:
        return _CACHE[key][1]
    try:
        b = _live_bundle(symbol)
    except Exception as e:
        if key in _SEED:
            b = _sample_bundle(symbol)
        else:
            # The live fetch failed for a ticker we have no sample for. This is
            # almost always Yahoo throttling (transient), NOT a bad symbol — say so
            # rather than implying the stock doesn't exist.
            raise ValueError(
                f"Couldn't fetch live data for '{_base(symbol)}' right now "
                f"(the market feed is rate-limiting or temporarily unreachable: {e}). "
                f"Wait a few seconds and try again. If it keeps failing, these "
                f"tickers also work offline: {', '.join(sorted(_SEED))}."
            )
    _CACHE[key] = (now, b)
    return b


# convenience accessors used as tools
def quote(s):
    """Freshest available quote. For live tickers this is the real-time spot
    price (short-cached ~20s) with the true day move; sample tickers return their
    bundled quote unchanged."""
    b = bundle(s)
    if b.get("source") == "live":
        try:
            return _cached_live_quote(s)
        except Exception:
            return b["quote"]        # live feed hiccup -> fall back to last close
    return b["quote"]
def price(s): return bundle(s)["price"]
def fundamentals(s): return bundle(s)["fundamentals"]
def news(s): return bundle(s)["news"]
def splits(s): return bundle(s)["splits"]
def dividends(s): return bundle(s)["dividends"]
def week52(s): return bundle(s)["week52"]
def chart(s): return bundle(s)["chart"]
def analyst_ratings(s): return bundle(s).get("analyst", {})
def stats(s): return bundle(s).get("stats", {})


def quarterly(s):
    """Recent quarterly revenue & net income in ₹ crore (live-only, best-effort)."""
    try:
        import yfinance as yf
        q = yf.Ticker(_nse(s)).quarterly_income_stmt
        if q is None or q.empty:
            return []
        out = []
        for col in list(q.columns)[:4]:
            rev = q.at["Total Revenue", col] if "Total Revenue" in q.index else None
            ni = q.at["Net Income", col] if "Net Income" in q.index else None
            cr = lambda v: round(float(v) / 1e7) if v is not None and v == v else None
            out.append({"quarter": str(getattr(col, "date", lambda: col)()),
                        "revenue_cr": cr(rev), "net_income_cr": cr(ni)})
        return out
    except Exception:
        return []


def performance(s):
    """Simple % moves derived from the chart series."""
    b = bundle(s)
    # keep only real, finite closes (NaN != NaN) so a bad row can't poison the math
    ser = [p["close"] for p in b["chart"]
           if isinstance(p.get("close"), (int, float)) and p["close"] == p["close"]]
    if len(ser) < 2:
        return {}
    return {"period_change_pct": round((ser[-1] / ser[0] - 1) * 100, 2),
            "last_close": ser[-1], "high": max(ser), "low": min(ser)}


def valuation(s):
    f = bundle(s)["fundamentals"]
    return {k: f.get(k) for k in ("pe", "pb", "market_cap", "market_cap_cr", "dividend_yield_pct") if f.get(k) is not None}


def list_supported():
    return sorted(_SEED)