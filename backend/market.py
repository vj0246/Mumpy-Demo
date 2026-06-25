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
# News: Google News RSS (real, current headlines) with a yfinance fallback
# --------------------------------------------------------------------------- #
def _google_news(query: str, n: int = 6) -> list:
    """Recent headlines from Google News RSS — far fresher and more relevant than
    yfinance's news feed. Returns [] on any failure so the caller can fall back."""
    try:
        import xml.etree.ElementTree as ET
        from urllib.parse import quote as _q
        try:
            from curl_cffi import requests as _creq
            r = _creq.get(f"https://news.google.com/rss/search?q={_q(query)}&hl=en-IN&gl=IN&ceid=IN:en",
                          impersonate="chrome", timeout=8)
            text = r.text
        except Exception:
            import urllib.request
            req = urllib.request.Request(
                f"https://news.google.com/rss/search?q={_q(query)}&hl=en-IN&gl=IN&ceid=IN:en",
                headers={"User-Agent": "Mozilla/5.0"})
            text = urllib.request.urlopen(req, timeout=8).read().decode("utf-8", "ignore")
        root = ET.fromstring(text)
        out = []
        for it in root.findall(".//item")[:n]:
            title = (it.findtext("title") or "").strip()
            if title:
                out.append({"headline": title, "sentiment": "n/a"})
        return out
    except Exception:
        return []


def _yf_news(tk, n: int = 6) -> list:
    out = []
    try:
        for nws in (tk.news or [])[:n]:
            c = nws.get("content", nws)
            h = c.get("title") or nws.get("title", "")
            if h:
                out.append({"headline": h, "sentiment": "n/a"})
    except Exception:
        pass
    return out


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

    price = closes[-1]

    # fast_info: lightweight + reliable shares and market cap (no .info dependency).
    fi_shares = fi_mktcap = None
    try:
        fi = tk.fast_info
        fi_shares = _num(getattr(fi, "shares", None))
        fi_mktcap = _num(getattr(fi, "market_cap", None))
    except Exception:
        pass

    # .info is SUPPLEMENTARY only — it is often empty/throttled for NSE names, which
    # was the bug behind "Valuation: {}". We never depend on it for core ratios.
    info = {}
    try:
        info = tk.info or {}
    except Exception:
        pass
    def _pct(v):
        return round(v * 100, 2) if isinstance(v, (int, float)) and v == v else None

    # Financial statements: the reliable backbone for fundamentals.
    qresults = _quarterly_from(tk)
    bsheet = _balance_sheet_from(tk)

    def _sum4(key):
        vals = [q[key] for q in qresults[:4] if q.get(key) is not None]
        return sum(vals) if len(vals) >= 4 else None
    ttm_ni_cr = _sum4("net_income_cr")
    ttm_rev_cr = _sum4("revenue_cr")
    ttm_op_cr = _sum4("operating_income_cr")
    equity_cr = bsheet.get("shareholders_equity_cr")
    debt_cr = bsheet.get("total_debt_cr")

    mc = fi_mktcap or _num(info.get("marketCap")) or (fi_shares * price if fi_shares else None)
    mc_cr = round(mc / 1e7) if mc else None

    # Derive ratios from primary data (market cap, trailing profit, equity); fall back
    # to .info only when a component is missing.
    pe = (round(mc_cr / ttm_ni_cr, 2) if (mc_cr and ttm_ni_cr and ttm_ni_cr > 0)
          else _num(info.get("trailingPE")))
    pb = (round(mc_cr / equity_cr, 2) if (mc_cr and equity_cr and equity_cr > 0)
          else _num(info.get("priceToBook")))
    roe = (round(ttm_ni_cr / equity_cr * 100, 2) if (ttm_ni_cr and equity_cr and equity_cr > 0)
           else _pct(info.get("returnOnEquity")))
    net_margin = (round(ttm_ni_cr / ttm_rev_cr * 100, 2) if (ttm_ni_cr and ttm_rev_cr and ttm_rev_cr > 0)
                  else _pct(info.get("profitMargins")))
    if debt_cr is not None and equity_cr:
        d2e = round(debt_cr / equity_cr, 2)
    elif isinstance(info.get("debtToEquity"), (int, float)):
        d2e = round(info["debtToEquity"] / 100, 2)        # yfinance reports it ×100
    else:
        d2e = None
    eps_ttm = round(ttm_ni_cr * 1e7 / fi_shares, 2) if (ttm_ni_cr and fi_shares) else None

    fundamentals = {"pe": pe, "pb": pb, "market_cap": mc, "market_cap_cr": mc_cr,
                    "net_margin_pct": net_margin, "roe_pct": roe,
                    "dividend_yield_pct": None, "debt_to_equity": d2e,
                    "eps_ttm": eps_ttm, "revenue_ttm_cr": ttm_rev_cr}

    # Splits & dividends
    splits, dividends, dvs = [], [], None
    try:
        splits = [{"date": str(i.date()), "ratio": float(r)} for i, r in tk.splits.items()][-8:]
    except Exception:
        pass
    try:
        dvs = tk.dividends
        dividends = [{"year": i.year, "amount": round(float(v), 2)} for i, v in dvs.items()][-6:]
    except Exception:
        pass
    try:
        import pandas as pd
        if dvs is not None and not dvs.empty:
            now = pd.Timestamp.now(tz=dvs.index.tz)
            ttm_div = float(dvs[dvs.index >= now - pd.Timedelta(days=365)].sum())
            if ttm_div > 0:
                fundamentals["dividend_yield_pct"] = round(ttm_div / price * 100, 2)
    except Exception:
        pass
    if fundamentals["dividend_yield_pct"] is None and isinstance(info.get("dividendYield"), (int, float)):
        fundamentals["dividend_yield_pct"] = info["dividendYield"]
    fundamentals = {k: v for k, v in fundamentals.items() if v is not None}

    # Extended stats — compute what we can so it isn't empty when .info is throttled.
    ma50 = round(sum(closes[-50:]) / min(50, len(closes)), 2) if len(closes) >= 20 else None
    def _yoy(key):
        if len(qresults) >= 4 and qresults[0].get(key) and qresults[3].get(key):
            try:
                return round((qresults[0][key] / qresults[3][key] - 1) * 100, 2)
            except Exception:
                return None
        return None
    rg, eg = _yoy("revenue_cr"), _yoy("net_income_cr")
    op_margin = (round(ttm_op_cr / ttm_rev_cr * 100, 2) if (ttm_op_cr and ttm_rev_cr and ttm_rev_cr > 0)
                 else _pct(info.get("operatingMargins")))
    stats = {"beta": info.get("beta"), "ma50": ma50, "ma200": info.get("twoHundredDayAverage"),
             "revenue_growth_pct": rg if rg is not None else _pct(info.get("revenueGrowth")),
             "earnings_growth_pct": eg if eg is not None else _pct(info.get("earningsGrowth")),
             "operating_margin_pct": op_margin, "gross_margin_pct": _pct(info.get("grossMargins")),
             "current_ratio": info.get("currentRatio")}
    stats = {k: v for k, v in stats.items() if v is not None}

    analyst = {"target_mean": info.get("targetMeanPrice"), "target_high": info.get("targetHighPrice"),
               "target_low": info.get("targetLowPrice"), "recommendation": info.get("recommendationKey"),
               "num_analysts": info.get("numberOfAnalystOpinions"), "current_price": price}
    analyst = {k: v for k, v in analyst.items() if v is not None}

    try:
        avg_volume_m = round(float(hist["Volume"].tail(20).mean()) / 1e6, 2)
    except Exception:
        avg_volume_m = round((info.get("averageVolume") or 0) / 1e6, 2)

    # News: Google News RSS first (current + relevant), yfinance as a fallback.
    name = info.get("shortName") or _base(symbol)
    news = _google_news(f"{name} share price NSE") or _yf_news(tk)

    return {
        "ticker": _base(symbol), "name": name, "source": "live",
        "quote": {"price": price, "change_pct": change},
        "price": {"period": "6mo", "start": closes[0], "end": price,
                  "high": max(closes), "low": min(closes), "change_pct": change,
                  "avg_volume_m": avg_volume_m},
        "week52": {"high": info.get("fiftyTwoWeekHigh"), "low": info.get("fiftyTwoWeekLow")},
        "fundamentals": fundamentals, "news": news,
        "splits": splits, "dividends": dividends, "chart": chart,
        "analyst": analyst, "stats": stats,
        "quarterly_results": qresults, "balance_sheet": bsheet,
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


_FX: dict = {}


def _usd_to_inr() -> float:
    """USD→INR rate (cached 1h). Falls back to a recent constant if the FX feed fails."""
    now = time.time()
    if "rate" in _FX and now - _FX["t"] < 3600:
        return _FX["rate"]
    rate = None
    try:
        import yfinance as yf
        try:
            from curl_cffi import requests as _creq
            fx = yf.Ticker("INR=X", session=_creq.Session(impersonate="chrome"))
        except Exception:
            fx = yf.Ticker("INR=X")
        try:
            rate = float(fx.fast_info.last_price)
        except Exception:
            h = fx.history(period="5d").dropna(subset=["Close"])
            if not h.empty:
                rate = float(h["Close"].iloc[-1])
    except Exception:
        pass
    rate = rate if (rate and rate == rate and rate > 1) else 86.0
    _FX["rate"], _FX["t"] = rate, now
    return rate


def _inr_scale(tk, sample) -> float:
    """Multiplier to convert a raw income/balance-sheet value to INR.

    yfinance reports some US-cross-listed Indian names (e.g. INFY) in USD. The
    `financialCurrency` flag alone is unreliable (HCLTECH is wrongly tagged USD),
    so we only convert when BOTH the flag says USD AND the magnitude looks like USD
    (genuine USD figures are ~80x smaller than the INR equivalent). Large values
    (>= ₹5,000cr-ish raw) are treated as INR without even fetching `.info`."""
    try:
        if sample is None or abs(float(sample)) >= 5e10:
            return 1.0          # clearly INR magnitude — skip the heavy .info call
    except Exception:
        return 1.0
    try:
        if (tk.info or {}).get("financialCurrency") == "USD":
            return _usd_to_inr()
    except Exception:
        pass
    return 1.0


def _quarterly_from(tk):
    """Quarterly results (₹ crore + EPS), INR-normalised. Works off the income
    statement, which is far more reliable than the .info endpoint."""
    try:
        q = tk.quarterly_income_stmt
        if q is None or q.empty:
            return []
        def at(row, col):
            return q.at[row, col] if row in q.index else None
        scale = _inr_scale(tk, at("Total Revenue", q.columns[0]))
        cr = lambda v: round(float(v) * scale / 1e7) if v is not None and v == v else None
        num = lambda v: round(float(v) * scale, 2) if v is not None and v == v else None
        out = []
        for col in list(q.columns)[:4]:
            out.append({"quarter": str(getattr(col, "date", lambda: col)()),
                        "revenue_cr": cr(at("Total Revenue", col)),
                        "net_income_cr": cr(at("Net Income", col)),
                        "operating_income_cr": cr(at("Operating Income", col)),
                        "eps": num(at("Basic EPS", col))})
        return out
    except Exception:
        return []


def quarterly(s):
    """Recent quarterly revenue, net profit, operating income (₹ crore) and EPS
    (INR-normalised so peer comparisons are apples-to-apples even when yfinance
    reports a peer in USD)."""
    return _quarterly_from(_ticker(s))


def _balance_sheet_from(tk):
    """Key balance-sheet items in ₹ crore (INR-normalised). Works off the balance
    sheet statement, independent of the flaky .info endpoint."""
    try:
        bs = tk.quarterly_balance_sheet
        if bs is None or bs.empty:
            bs = tk.balance_sheet
        if bs is None or bs.empty:
            return {}
        col = bs.columns[0]
        raw_assets = bs.at["Total Assets", col] if "Total Assets" in bs.index else None
        scale = _inr_scale(tk, raw_assets)        # normalise USD-reported names to INR
        def cr(*rows):
            for r in rows:
                if r in bs.index:
                    v = bs.at[r, col]
                    if v is not None and v == v:
                        return round(float(v) * scale / 1e7)
            return None
        out = {
            "as_of": str(getattr(col, "date", lambda: col)()),
            "shareholders_equity_cr": cr("Stockholders Equity", "Common Stock Equity"),
            "total_assets_cr": cr("Total Assets"),
            "total_liabilities_cr": cr("Total Liabilities Net Minority Interest"),
            "total_debt_cr": cr("Total Debt"),
            "cash_cr": cr("Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"),
            "retained_earnings_cr": cr("Retained Earnings"),
            "working_capital_cr": cr("Working Capital"),
        }
        try:
            # NOTE: info.bookValue is in the PRICE currency (INR for NSE), not the
            # statement currency, so it must NOT be scaled by `scale`.
            bv = (tk.info or {}).get("bookValue")
            out["book_value_per_share"] = round(float(bv), 2) if bv is not None else None
        except Exception:
            pass
        return {k: v for k, v in out.items() if v is not None}
    except Exception:
        return {}


def balance_sheet(s):
    """Key balance-sheet items in ₹ crore: shareholders' equity, total assets &
    liabilities, debt, cash, retained earnings, working capital, book value/share."""
    return _balance_sheet_from(_ticker(s))


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