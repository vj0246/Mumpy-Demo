import { useState, useRef, useEffect } from "react";
import Chart from "./Chart.jsx";
import TickerSearch from "./TickerSearch.jsx";
import { API } from "./api.js";

const SUGGEST = ["Do a fundamental analysis", "Why did it fall recently?", "Technical view & chart", "Bull vs bear case", "Buy, hold or sell?"];
const DOC_SUGGEST = ["Summarise the uploaded document", "What's the net profit & revenue?", "Key risks mentioned in the document"];

const TOOL_LABEL = {
  get_quote: "Quote", get_price_chart: "Chart", get_fundamentals: "Fundamentals",
  get_valuation: "Valuation", get_fundamental_analysis: "Fundamental analysis",
  get_technical_analysis: "Technical analysis", explain_price_move: "Reason for the move",
  get_risk_assessment: "Risk assessment", get_bull_bear_case: "Bull vs bear",
  analyze_news_sentiment: "News sentiment", get_news_headlines: "News headlines",
  get_splits: "Stock splits", get_dividends: "Dividends", get_52week_range: "52-week range",
  get_performance: "Performance", get_analyst_ratings: "Analyst ratings",
  get_quarterly_results: "Quarterly results", get_key_stats: "Key stats",
  ask_document: "Document Q&A", deep_desk_analysis: "Desk analysis",
};

export default function Chat() {
  const [ticker, setTicker] = useState("RELIANCE");
  const [msgs, setMsgs] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [doc, setDoc] = useState(null);        // { name, chars } of the attached document
  const [uploading, setUploading] = useState(false);
  const esRef = useRef(null);
  const thread = useRef(crypto.randomUUID());
  const fileRef = useRef(null);
  const bottom = useRef(null);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  function reset() {
    if (esRef.current) esRef.current.close();
    if (doc) { fetch(`${API}/api/upload?thread=${thread.current}`, { method: "DELETE" }).catch(() => {}); }
    thread.current = crypto.randomUUID();   // fresh conversation memory
    setMsgs([]); setInput(""); setBusy(false); setDoc(null);
  }

  async function onFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("thread", thread.current);
      fd.append("file", file);
      const r = await fetch(`${API}/api/upload`, { method: "POST", body: fd });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Upload failed");
      setDoc({ name: d.name, chars: d.chars });
      setMsgs((m) => [...m, { role: "assistant", steps: [], chart: null,
        answer: `📄 Attached “${d.name}” (${d.chars.toLocaleString()} characters extracted). Ask me anything about it.`, loading: false }]);
    } catch (err) {
      setMsgs((m) => [...m, { role: "assistant", steps: [], chart: null, answer: "⚠ " + err.message, loading: false }]);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";   // allow re-uploading the same file
    }
  }

  function removeDoc() {
    fetch(`${API}/api/upload?thread=${thread.current}`, { method: "DELETE" }).catch(() => {});
    setDoc(null);
  }

  function ask(text) {
    const q = (text ?? input).trim();
    if (!q || busy) return;
    setInput("");
    setBusy(true);
    setMsgs((m) => [...m, { role: "user", text: q }, { role: "assistant", steps: [], chart: null, answer: "", loading: true }]);

    if (esRef.current) esRef.current.close();
    const url = `${API}/api/chat?ticker=${encodeURIComponent(ticker)}&q=${encodeURIComponent(q)}&thread=${thread.current}`;
    const es = new EventSource(url);
    esRef.current = es;

    es.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.type === "done") { es.close(); setBusy(false); setMsgs((m) => patchLast(m, { loading: false })); return; }
      setMsgs((m) => {
        const last = m[m.length - 1];
        if (last?.role !== "assistant") return m;
        if (ev.type === "tool_call") return patchLast(m, { steps: [...last.steps, { name: ev.name, args: ev.args }] });
        if (ev.type === "chart") return patchLast(m, { chart: { series: ev.series, ticker: ev.ticker, changePct: ev.change_pct } });
        if (ev.type === "answer") return patchLast(m, { answer: ev.text });
        if (ev.type === "tool_result") return m; // kept quiet; tool_call already shown
        if (ev.type === "error") return patchLast(m, { answer: "⚠ " + ev.text });
        return m;
      });
    };
    es.onerror = () => { es.close(); setBusy(false); setMsgs((m) => patchLast(m, { loading: false, answer: m[m.length - 1].answer || "⚠ Connection dropped. Is the backend running?" })); };
  }

  return (
    <div className="chat">
      <div className="chat-top">
        <div className="chat-title-row">
          <div className="chat-title">Ask about a stock</div>
          <button className="chat-refresh" onClick={reset} disabled={busy} title="Clear chat & start fresh" aria-label="Clear chat">↻ New</button>
        </div>
        <div className="chat-sub">Free-form Q&amp;A — it answers instantly and picks its own tools, no step-by-step approvals. (The Analyst on the left works one approved step at a time.)</div>
        <div className="chat-ticker-row">
          <span className="nse">NSE</span>
          <TickerSearch value={ticker} onChange={setTicker} placeholder="Search company or symbol" />
        </div>
        <div className="chat-upload">
          <button className="upload-btn" onClick={() => fileRef.current?.click()} disabled={uploading}>
            {uploading ? "Uploading…" : "📎 Attach PDF / Word"}
          </button>
          <input ref={fileRef} type="file" accept=".pdf,.docx,.txt,.md,.csv" onChange={onFile} hidden />
          {doc && (
            <span className="doc-chip" title={doc.name}>
              <span className="doc-name">📄 {doc.name}</span>
              <button onClick={removeDoc} aria-label="Remove document" title="Remove">×</button>
            </span>
          )}
        </div>
      </div>

      <div className="chat-body">
        {msgs.length === 0 && (
          <div className="chat-empty">
            <p>{doc ? "Ask about the stock or your attached document." : "Pick a stock, ask anything. Or attach a PDF / Word doc above and ask about it."}</p>
            <div className="suggest">
              {(doc ? DOC_SUGGEST : SUGGEST).map((s) => <button key={s} onClick={() => ask(s)}>{s}</button>)}
            </div>
          </div>
        )}
        {msgs.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="bubble user">{m.text}</div>
          ) : (
            <div key={i} className="bubble bot">
              {m.steps.length > 0 && (
                <div className="steps">
                  {m.steps.map((s, j) => <span key={j} className="step-chip">{TOOL_LABEL[s.name] || s.name}</span>)}
                </div>
              )}
              {m.chart && <Chart series={m.chart.series} ticker={m.chart.ticker} changePct={m.chart.changePct} />}
              {m.answer && <div className="bot-text">{m.answer}</div>}
              {m.loading && !m.answer && <div className="dots"><i /><i /><i /></div>}
            </div>
          )
        )}
        <div ref={bottom} />
      </div>

      <div className="chat-input">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask()}
          placeholder={`Ask about ${ticker}…`}
          disabled={busy}
        />
        <button onClick={() => ask()} disabled={busy || !input.trim()}>Send</button>
      </div>
    </div>
  );
}

function patchLast(arr, patch) {
  const copy = arr.slice();
  copy[copy.length - 1] = { ...copy[copy.length - 1], ...patch };
  return copy;
}
