import { useState, useEffect, useRef } from "react";
import { API } from "./api.js";

/**
 * Search-bar with a company-name + ticker autocomplete dropdown.
 * Typing still sets the symbol live (old behaviour), but now you can pick a
 * company by name from the list and it fills in the right NSE ticker.
 */
export default function TickerSearch({ value, onChange, disabled, placeholder }) {
  const [query, setQuery] = useState(value || "");
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(-1);
  const boxRef = useRef(null);
  const tmr = useRef(null);

  // follow the symbol when it's changed elsewhere
  useEffect(() => { setQuery(value || ""); }, [value]);

  // close the dropdown on an outside click
  useEffect(() => {
    function onDoc(e) { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false); }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  function suggest(q) {
    clearTimeout(tmr.current);
    tmr.current = setTimeout(async () => {
      try {
        const r = await fetch(`${API}/api/symbols?q=${encodeURIComponent(q)}`);
        const d = await r.json();
        setResults(d.results || []);
        setHi(-1);
      } catch { setResults([]); }
    }, 120);
  }

  function handleChange(e) {
    const v = e.target.value.toUpperCase();
    setQuery(v);
    onChange?.(v);
    setOpen(true);
    suggest(v);
  }

  function pick(item) {
    setQuery(item.ticker);
    onChange?.(item.ticker);
    setOpen(false);
    setResults([]);
  }

  function onKey(e) {
    if (!open || results.length === 0) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setHi((h) => Math.min(h + 1, results.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)); }
    else if (e.key === "Enter" && hi >= 0) { e.preventDefault(); pick(results[hi]); }
    else if (e.key === "Escape") { setOpen(false); }
  }

  return (
    <div className="ts" ref={boxRef}>
      <input
        className="ticker-input"
        value={query}
        onChange={handleChange}
        onFocus={() => { setOpen(true); suggest(query); }}
        onKeyDown={onKey}
        placeholder={placeholder || "Search company or symbol"}
        spellCheck={false}
        autoComplete="off"
        disabled={disabled}
      />
      {open && results.length > 0 && (
        <ul className="ts-list">
          {results.map((it, i) => (
            <li
              key={it.ticker}
              className={"ts-item" + (i === hi ? " hi" : "")}
              onMouseDown={(e) => { e.preventDefault(); pick(it); }}
              onMouseEnter={() => setHi(i)}
            >
              <span className="ts-tkr">{it.ticker}</span>
              <span className="ts-name">{it.name}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
