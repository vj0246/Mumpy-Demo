import { useState, useRef, useEffect } from "react";
import Chart from "./Chart.jsx";
import TickerSearch from "./TickerSearch.jsx";
import { API } from "./api.js";

const PRESETS = [
  ["Fundamental analysis", "Do a fundamental analysis: financial health, valuation and quality verdict."],
  ["Technical analysis", "Give a technical read of the price trend and momentum."],
  ["Why did it move?", "Explain the reason for the recent rise or downfall."],
  ["Risk assessment", "Assess the key downside risks for this stock right now."],
  ["Bull vs bear", "Lay out the bull case versus the bear case."],
  ["News & sentiment", "Summarise the latest news and judge the market sentiment."],
  ["Quarterly results", "Review the latest quarterly results and what they show."],
  ["Buy / hold / sell", "Give me a full analysis and a clear buy / hold / sell verdict."],
];

const TOOL_LABEL = {
  quote: "Quote", fifty_two_week: "52-week range", performance: "Performance",
  price_trend: "Price trend", fundamentals: "Fundamentals", valuation: "Valuation",
  fundamental_analysis: "Fundamental analysis", quarterly_results: "Quarterly results",
  key_stats: "Key stats", dividends: "Dividends", dividend_analysis: "Dividend analysis",
  stock_splits: "Stock splits", technical_analysis: "Technical analysis",
  explain_move: "Reason for the move", news_sentiment: "News sentiment",
  news_headlines: "News headlines", news_summary: "News summary",
  analyst_ratings: "Analyst ratings", risk_assessment: "Risk assessment",
  bull_bear_case: "Bull vs bear", verdict: "Verdict", finish: "Finalise",
};

export default function Analyst() {
  const [ticker, setTicker] = useState("");
  const [task, setTask] = useState("");
  const [items, setItems] = useState([]);          // timeline: intro/step/chart/final
  const [pending, setPending] = useState(null);    // {tool, summary}
  const [phase, setPhase] = useState("idle");      // idle | working | awaiting | done
  const [redirect, setRedirect] = useState("");
  const esRef = useRef(null);
  const thread = useRef(null);
  const bottom = useRef(null);
  const phaseRef = useRef("idle");

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [items, pending]);

  function listen(url) {
    if (esRef.current) esRef.current.close();
    setPhase("working"); phaseRef.current = "working"; setPending(null);
    const es = new EventSource(url);
    esRef.current = es;
    es.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      if (ev.type === "done") { es.close(); if (phaseRef.current === "working") setPhase("idle"); return; }
      if (ev.type === "propose") { setPending({ tool: ev.tool, summary: ev.summary }); setPhase("awaiting"); phaseRef.current = "awaiting"; es.close(); return; }
      if (ev.type === "final") { setItems((p) => [...p, { kind: "final", text: ev.text }]); setPhase("done"); phaseRef.current = "done"; es.close(); return; }
      if (ev.type === "intro") setItems((p) => [...p, { kind: "intro", text: ev.text }]);
      else if (ev.type === "step_result") setItems((p) => [...p, { kind: "step", tool: ev.tool, text: ev.text }]);
      else if (ev.type === "chart") setItems((p) => [...p, { kind: "chart", series: ev.series, ticker: ev.ticker, changePct: ev.change_pct }]);
      else if (ev.type === "error") setItems((p) => [...p, { kind: "error", text: ev.text }]);
    };
    es.onerror = () => { es.close(); setItems((p) => [...p, { kind: "error", text: "Stream dropped. Is the backend running?" }]); setPhase("idle"); phaseRef.current = "idle"; };
  }

  function start() {
    if (!ticker.trim() || !task.trim() || phase === "working") return;
    thread.current = crypto.randomUUID();
    setItems([]); setPending(null); setRedirect("");
    listen(`${API}/api/task/start?ticker=${encodeURIComponent(ticker.trim())}&task=${encodeURIComponent(task.trim())}&thread=${thread.current}`);
  }

  function decide(decision) {
    listen(`${API}/api/task/step?thread=${thread.current}&decision=${encodeURIComponent(decision)}`);
  }

  const running = phase === "working";

  return (
    <div className="desk">
      <div className="eyebrow">Task agent · step-by-step approval · NSE</div>
      <h1>Analyst Agent</h1>
      <p className="sub">Give it a stock and a task. It proposes one step at a time — you approve, redirect, or stop. It acts only with your sign-off.</p>

      <div className="task-setup">
        <div className="row1">
          <span className="nse">NSE</span>
          <TickerSearch value={ticker} onChange={setTicker} disabled={running} placeholder="Search company or symbol, e.g. RELIANCE" />
        </div>
        <div className="presets">
          {PRESETS.map(([label, t]) => (
            <button key={label} className="preset" onClick={() => setTask(t)} disabled={running}>{label}</button>
          ))}
        </div>
        <div className="row2">
          <input className="task-input" value={task} onChange={(e) => setTask(e.target.value)} onKeyDown={(e) => e.key === "Enter" && start()} placeholder="…or type your own task" disabled={running} />
          <button className="run" onClick={start} disabled={running || !ticker.trim() || !task.trim()}>Start</button>
        </div>
      </div>

      {items.length === 0 && phase === "idle" && (
        <div className="empty">Enter a stock and a task to begin. The agent will ask before each step.</div>
      )}

      <div className="spine">
        {items.map((it, i) => (
          it.kind === "intro" ? (
            <div key={i} className="event"><span className="node plan" /><div className="plan-text">{it.text}</div></div>
          ) : it.kind === "step" ? (
            <div key={i} className="event" style={{ "--c": "var(--think)" }}><span className="node role" /><div className="label" style={{ color: "var(--think)" }}>{TOOL_LABEL[it.tool] || it.tool}</div><div className="plan-text" style={{ whiteSpace: "pre-wrap", fontStyle: "normal" }}>{it.text}</div></div>
          ) : it.kind === "chart" ? (
            <div key={i} className="event"><span className="node role" style={{ "--c": "var(--signal)" }} /><Chart series={it.series} ticker={it.ticker} changePct={it.changePct} /></div>
          ) : it.kind === "final" ? (
            <div key={i} className="event"><span className="node final" /><div className="label">final report</div><div className="verdict"><div className="thesis" style={{ whiteSpace: "pre-wrap" }}>{it.text}</div></div></div>
          ) : (
            <div key={i} className="event"><span className="node plan" /><div className="err">⚠ {it.text}</div></div>
          )
        ))}
        {running && <div className="event"><span className="node tool_call" /><div className="thinking"><i /><i /><i /></div></div>}
        <div ref={bottom} />
      </div>

      {phase === "awaiting" && pending && (
        <div className="gate">
          <div className="gate-tag">{pending.tool === "finish" ? "⏸ Ready to finalise" : "⏸ Next step — your call"}</div>
          <div className="gate-action"><span>Proposed step · {TOOL_LABEL[pending.tool] || pending.tool}</span>{pending.summary}</div>
          <div className="gate-btns">
            <button className="approve" onClick={() => decide("approve")}>{pending.tool === "finish" ? "Approve & get report" : "Approve"}</button>
            <button className="reject" onClick={() => decide("stop")}>Stop & summarise</button>
          </div>
          {pending.tool !== "finish" && (
            <div className="revise">
              <input value={redirect} onChange={(e) => setRedirect(e.target.value)} placeholder="…or redirect (e.g. 'check fundamentals instead')" />
              <button onClick={() => redirect.trim() && (decide("redirect:" + redirect.trim()), setRedirect(""))} disabled={!redirect.trim()}>Redirect</button>
            </div>
          )}
        </div>
      )}

      <div className="footnote">Informational only, not investment advice. The agent proposes; you approve each step.</div>
    </div>
  );
}
