"""
companies.py
------------
A directory of common NSE stocks (symbol + company name) that powers the
search-bar autocomplete. This is a static reference list for type-ahead only;
the actual numbers always come from market.py (live yfinance, sample fallback).

`search(q)` ranks matches so the dropdown feels natural: exact ticker first,
then ticker prefix, then name matches.
"""

from seed_data import SEEDS

# Curated set of widely-traded NSE names. Symbols are NSE tickers (no ".NS").
# Not exhaustive — extend freely; market.py will fetch anything you type.
COMPANIES = [
    ("RELIANCE", "Reliance Industries Ltd"),
    ("TCS", "Tata Consultancy Services Ltd"),
    ("INFY", "Infosys Ltd"),
    ("HDFCBANK", "HDFC Bank Ltd"),
    ("ICICIBANK", "ICICI Bank Ltd"),
    ("SBIN", "State Bank of India"),
    ("HINDUNILVR", "Hindustan Unilever Ltd"),
    ("ITC", "ITC Ltd"),
    ("BHARTIARTL", "Bharti Airtel Ltd"),
    ("LT", "Larsen & Toubro Ltd"),
    ("KOTAKBANK", "Kotak Mahindra Bank Ltd"),
    ("AXISBANK", "Axis Bank Ltd"),
    ("BAJFINANCE", "Bajaj Finance Ltd"),
    ("BAJAJFINSV", "Bajaj Finserv Ltd"),
    ("ASIANPAINT", "Asian Paints Ltd"),
    ("MARUTI", "Maruti Suzuki India Ltd"),
    ("HCLTECH", "HCL Technologies Ltd"),
    ("WIPRO", "Wipro Ltd"),
    ("TECHM", "Tech Mahindra Ltd"),
    ("SUNPHARMA", "Sun Pharmaceutical Industries Ltd"),
    ("TATAMOTORS", "Tata Motors Ltd"),
    ("TATASTEEL", "Tata Steel Ltd"),
    ("TATAPOWER", "Tata Power Company Ltd"),
    ("TATACONSUM", "Tata Consumer Products Ltd"),
    ("TITAN", "Titan Company Ltd"),
    ("NESTLEIND", "Nestle India Ltd"),
    ("ULTRACEMCO", "UltraTech Cement Ltd"),
    ("GRASIM", "Grasim Industries Ltd"),
    ("JSWSTEEL", "JSW Steel Ltd"),
    ("HINDALCO", "Hindalco Industries Ltd"),
    ("COALINDIA", "Coal India Ltd"),
    ("ONGC", "Oil & Natural Gas Corporation Ltd"),
    ("NTPC", "NTPC Ltd"),
    ("POWERGRID", "Power Grid Corporation of India Ltd"),
    ("ADANIENT", "Adani Enterprises Ltd"),
    ("ADANIPORTS", "Adani Ports & SEZ Ltd"),
    ("ADANIGREEN", "Adani Green Energy Ltd"),
    ("ADANIPOWER", "Adani Power Ltd"),
    ("M&M", "Mahindra & Mahindra Ltd"),
    ("BAJAJ-AUTO", "Bajaj Auto Ltd"),
    ("HEROMOTOCO", "Hero MotoCorp Ltd"),
    ("EICHERMOT", "Eicher Motors Ltd"),
    ("DIVISLAB", "Divi's Laboratories Ltd"),
    ("DRREDDY", "Dr. Reddy's Laboratories Ltd"),
    ("CIPLA", "Cipla Ltd"),
    ("APOLLOHOSP", "Apollo Hospitals Enterprise Ltd"),
    ("BRITANNIA", "Britannia Industries Ltd"),
    ("DABUR", "Dabur India Ltd"),
    ("GODREJCP", "Godrej Consumer Products Ltd"),
    ("MARICO", "Marico Ltd"),
    ("PIDILITIND", "Pidilite Industries Ltd"),
    ("DMART", "Avenue Supermarts Ltd"),
    ("VBL", "Varun Beverages Ltd"),
    ("HAVELLS", "Havells India Ltd"),
    ("SIEMENS", "Siemens Ltd"),
    ("BOSCHLTD", "Bosch Ltd"),
    ("DLF", "DLF Ltd"),
    ("GODREJPROP", "Godrej Properties Ltd"),
    ("INDUSINDBK", "IndusInd Bank Ltd"),
    ("BANKBARODA", "Bank of Baroda"),
    ("PNB", "Punjab National Bank"),
    ("CANBK", "Canara Bank"),
    ("IDFCFIRSTB", "IDFC First Bank Ltd"),
    ("FEDERALBNK", "Federal Bank Ltd"),
    ("BANDHANBNK", "Bandhan Bank Ltd"),
    ("AUBANK", "AU Small Finance Bank Ltd"),
    ("SBILIFE", "SBI Life Insurance Company Ltd"),
    ("HDFCLIFE", "HDFC Life Insurance Company Ltd"),
    ("ICICIPRULI", "ICICI Prudential Life Insurance Company Ltd"),
    ("ICICIGI", "ICICI Lombard General Insurance Company Ltd"),
    ("LICI", "Life Insurance Corporation of India"),
    ("SHRIRAMFIN", "Shriram Finance Ltd"),
    ("CHOLAFIN", "Cholamandalam Investment & Finance Company Ltd"),
    ("MUTHOOTFIN", "Muthoot Finance Ltd"),
    ("PFC", "Power Finance Corporation Ltd"),
    ("RECLTD", "REC Ltd"),
    ("HDFCAMC", "HDFC Asset Management Company Ltd"),
    ("LTIM", "LTIMindtree Ltd"),
    ("PERSISTENT", "Persistent Systems Ltd"),
    ("COFORGE", "Coforge Ltd"),
    ("MPHASIS", "Mphasis Ltd"),
    ("OFSS", "Oracle Financial Services Software Ltd"),
    ("ETERNAL", "Eternal Ltd (formerly Zomato)"),
    ("PAYTM", "One 97 Communications Ltd (Paytm)"),
    ("JIOFIN", "Jio Financial Services Ltd"),
    ("NYKAA", "FSN E-Commerce Ventures Ltd (Nykaa)"),
    ("POLICYBZR", "PB Fintech Ltd (Policybazaar)"),
    ("IRCTC", "Indian Railway Catering & Tourism Corporation Ltd"),
    ("IRFC", "Indian Railway Finance Corporation Ltd"),
    ("BEL", "Bharat Electronics Ltd"),
    ("HAL", "Hindustan Aeronautics Ltd"),
    ("BHEL", "Bharat Heavy Electricals Ltd"),
    ("SAIL", "Steel Authority of India Ltd"),
    ("VEDL", "Vedanta Ltd"),
    ("JINDALSTEL", "Jindal Steel & Power Ltd"),
    ("NMDC", "NMDC Ltd"),
    ("GAIL", "GAIL (India) Ltd"),
    ("IOC", "Indian Oil Corporation Ltd"),
    ("BPCL", "Bharat Petroleum Corporation Ltd"),
    ("HINDPETRO", "Hindustan Petroleum Corporation Ltd"),
    ("PETRONET", "Petronet LNG Ltd"),
    ("AMBUJACEM", "Ambuja Cements Ltd"),
    ("ACC", "ACC Ltd"),
    ("SHREECEM", "Shree Cement Ltd"),
    ("DALBHARAT", "Dalmia Bharat Ltd"),
    ("PIIND", "PI Industries Ltd"),
    ("UPL", "UPL Ltd"),
    ("SRF", "SRF Ltd"),
    ("AARTIIND", "Aarti Industries Ltd"),
    ("DEEPAKNTR", "Deepak Nitrite Ltd"),
    ("LUPIN", "Lupin Ltd"),
    ("AUROPHARMA", "Aurobindo Pharma Ltd"),
    ("BIOCON", "Biocon Ltd"),
    ("ALKEM", "Alkem Laboratories Ltd"),
    ("TORNTPHARM", "Torrent Pharmaceuticals Ltd"),
    ("ZYDUSLIFE", "Zydus Lifesciences Ltd"),
    ("INDIGO", "InterGlobe Aviation Ltd (IndiGo)"),
    ("TRENT", "Trent Ltd"),
    ("PAGEIND", "Page Industries Ltd"),
    ("COLPAL", "Colgate-Palmolive (India) Ltd"),
    ("BERGEPAINT", "Berger Paints India Ltd"),
    ("MOTHERSON", "Samvardhana Motherson International Ltd"),
    ("BALKRISIND", "Balkrishna Industries Ltd"),
    ("ASHOKLEY", "Ashok Leyland Ltd"),
    ("TVSMOTOR", "TVS Motor Company Ltd"),
    ("ABB", "ABB India Ltd"),
    ("CUMMINSIND", "Cummins India Ltd"),
    ("POLYCAB", "Polycab India Ltd"),
    ("INDHOTEL", "The Indian Hotels Company Ltd"),
    ("JUBLFOOD", "Jubilant FoodWorks Ltd"),
    ("NAUKRI", "Info Edge (India) Ltd"),
    ("LTTS", "L&T Technology Services Ltd"),
    ("GUJGASLTD", "Gujarat Gas Ltd"),
    ("IGL", "Indraprastha Gas Ltd"),
    ("MGL", "Mahanagar Gas Ltd"),
    ("MAXHEALTH", "Max Healthcare Institute Ltd"),
    ("LODHA", "Macrotech Developers Ltd (Lodha)"),
    ("OBEROIRLTY", "Oberoi Realty Ltd"),
    ("YESBANK", "Yes Bank Ltd"),
    ("IDEA", "Vodafone Idea Ltd"),
    ("ZEEL", "Zee Entertainment Enterprises Ltd"),
]

# Merge in any seeded tickers that aren't already listed, so the demo's offline
# sample symbols always appear in search.
_have = {sym for sym, _ in COMPANIES}
for _sym, _d in SEEDS.items():
    if _sym not in _have:
        COMPANIES.append((_sym, _d.get("name", _sym)))

_DIRECTORY = [{"ticker": t, "name": n} for t, n in COMPANIES]


def search(q: str, limit: int = 8) -> list[dict]:
    """Rank matches for the autocomplete dropdown.

    Order: exact ticker > ticker prefix > name starts-with > substring (ticker or
    name). With an empty query, return the first `limit` well-known names.
    """
    q = (q or "").strip().upper()
    if not q:
        return _DIRECTORY[:limit]

    def rank(item):
        t, n = item["ticker"], item["name"].upper()
        if t == q:
            return 0
        if t.startswith(q):
            return 1
        if n.startswith(q):
            return 2
        if q in t:
            return 3
        if q in n:
            return 4
        return 99

    scored = [(rank(it), it) for it in _DIRECTORY]
    scored = [(r, it) for r, it in scored if r < 99]
    scored.sort(key=lambda x: (x[0], x[1]["ticker"]))
    return [it for _, it in scored[:limit]]
