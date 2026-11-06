(() => {
  const HIDDEN = new Set(["ceramic", "keenable"]);
  const DISPLAY = new Map([["keenable-realtime", "Keenable"],
    ["google", "google/serper"], ["bing", "bing/searchapi"]]);
  const VERTICALS = new Map([["news", "News"], ["finance", "Finance"],
    ["scholar", "Scholar"], ["agentic_rare", "AgenticRare"], ["legal", "Legal"]]);
  const BENCHES = [
    ["news", "ndcg", "nDCG@5"],
    ["finance", "recall", "answer-recall@5"],
    ["scholar", "recall", "recall@10"],
    ["agentic_rare", "ndcg", "nDCG@5"],
    ["legal", "recall", "recall@5"],
  ];
  const nameOf = (e) => DISPLAY.get(e) ?? e;
  const vertOf = (b) => VERTICALS.get(b) ?? b;

  const wmean = (rows, metric) => {
    let sum = 0, w = 0;
    for (const r of rows) {
      const weight = r.num_scored;
      if (r[metric] == null || !Number.isFinite(weight) || weight <= 0) continue;
      sum += r[metric] * weight;
      w += weight;
    }
    return w ? sum / w : null;
  };

  const fmt = (v) => v == null ? "–" : v.toFixed(3);
  const fmtDelta = (a, b) => {
    if (a == null || b == null) return { text: "–", cls: "delta-zero" };
    const d = a - b;
    if (Math.abs(d) < 0.0005) return { text: "0.000", cls: "delta-zero" };
    return { text: `${d > 0 ? "+" : ""}${d.toFixed(3)}`, cls: d > 0 ? "delta-pos" : "delta-neg" };
  };

  const parseRows = (text) => text.split("\n").filter(Boolean).map((l) => JSON.parse(l));

  const windowRows = (rows, ms) => {
    if (!ms) return rows;
    const cutoff = Date.now() - ms;
    return rows.filter((r) => new Date(r.ts).getTime() >= cutoff);
  };

  const enginesIn = (rows) => {
    const seen = [];
    const have = new Set();
    for (const r of rows) {
      if (HIDDEN.has(r.engine) || have.has(r.engine)) continue;
      have.add(r.engine);
      seen.push(r.engine);
    }
    return seen;
  };

  const fillSelect = (sel, engines, fallback) => {
    const current = sel.value;
    sel.replaceChildren();
    for (const e of engines) {
      const opt = document.createElement("option");
      opt.value = e;
      opt.textContent = nameOf(e);
      sel.appendChild(opt);
    }
    sel.value = engines.includes(current) ? current
      : engines.includes(fallback) ? fallback
      : engines[0] || "";
  };

  const render = (state) => {
    const { rows, aSel, bSel, benchSel, windowSel, table, note } = state;
    const ms = Number(windowSel.value);
    const scoped = windowRows(rows, ms);
    const bench = benchSel.value;
    const a = aSel.value;
    const b = bSel.value;
    const slices = bench === "all" ? BENCHES : BENCHES.filter(([id]) => id === bench);
    table.replaceChildren();
    if (!a || !b || a === b) {
      note.textContent = a === b && a ? "Pick two different providers." : "Pick two providers.";
      return;
    }
    const head = document.createElement("tr");
    for (const h of ["vertical", "metric", nameOf(a), nameOf(b), "delta (A − B)"]) {
      const th = document.createElement("th");
      if (h !== "vertical" && h !== "metric") th.className = "num";
      th.textContent = h;
      head.appendChild(th);
    }
    table.appendChild(head);
    let n = 0;
    for (const [id, metric, label] of slices) {
      const br = scoped.filter((r) => r.bench === id);
      const av = wmean(br.filter((r) => r.engine === a), metric);
      const bv = wmean(br.filter((r) => r.engine === b), metric);
      if (av == null && bv == null) continue;
      n += 1;
      const tr = document.createElement("tr");
      const tdV = document.createElement("td");
      tdV.textContent = vertOf(id);
      const tdM = document.createElement("td");
      tdM.textContent = label;
      const tdA = document.createElement("td");
      tdA.className = "num";
      tdA.textContent = fmt(av);
      const tdB = document.createElement("td");
      tdB.className = "num";
      tdB.textContent = fmt(bv);
      if (av != null && bv != null) {
        if (av > bv) tdA.classList.add("cmp-winner");
        if (bv > av) tdB.classList.add("cmp-winner");
      }
      const delta = fmtDelta(av, bv);
      const tdD = document.createElement("td");
      tdD.className = `num ${delta.cls}`;
      tdD.textContent = delta.text;
      tr.append(tdV, tdM, tdA, tdB, tdD);
      table.appendChild(tr);
    }
    const windowLabel = ms === 7 * 86400e3 ? "last 7 days"
      : ms === 30 * 86400e3 ? "last 30 days"
      : "all published runs";
    note.textContent = n
      ? `Query-weighted mean of ${windowLabel}. Higher is better. Ultimate is the pooled ceiling, not a vendor.`
      : "No overlapping scored runs for this pair in the selected window.";
  };

  const boot = async () => {
    const aSel = document.getElementById("cmp-a");
    const bSel = document.getElementById("cmp-b");
    const benchSel = document.getElementById("cmp-bench");
    const windowSel = document.getElementById("cmp-window");
    const table = document.getElementById("cmp-table");
    const note = document.getElementById("cmp-note");
    if (!aSel || !bSel || !table) return;
    const root = document.documentElement.dataset.root || ".";
    let rows = [];
    try {
      const resp = await fetch(`${root}/data/history.jsonl`, { cache: "no-store" });
      rows = resp.ok ? parseRows(await resp.text()) : [];
    } catch {
      rows = [];
    }
    const engines = enginesIn(rows);
    const params = new URLSearchParams(location.search);
    const wantA = params.get("a") || "keenable-realtime";
    const wantB = params.get("b") || "exa";
    fillSelect(aSel, engines, wantA);
    fillSelect(bSel, engines, wantB);
    if (engines.includes(wantA)) aSel.value = wantA;
    if (engines.includes(wantB)) bSel.value = wantB;
    if (params.get("bench")) benchSel.value = params.get("bench");
    if (params.get("window")) windowSel.value = params.get("window");
    const state = { rows, aSel, bSel, benchSel, windowSel, table, note };
    const syncUrl = () => {
      const next = new URL(location.href);
      next.searchParams.set("a", aSel.value);
      next.searchParams.set("b", bSel.value);
      next.searchParams.set("bench", benchSel.value);
      next.searchParams.set("window", windowSel.value);
      history.replaceState(null, "", next);
    };
    const draw = () => { render(state); syncUrl(); };
    for (const el of [aSel, bSel, benchSel, windowSel]) el.addEventListener("change", draw);
    draw();
  };

  boot();
})();
