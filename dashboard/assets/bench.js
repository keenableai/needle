(() => {
  const HIDDEN = new Set(["ceramic", "keenable"]);
  const DISPLAY = new Map([["keenable-realtime", "Keenable"],
    ["google", "google/serper"], ["bing", "bing/searchapi"]]);
  const METRICS = {
    news: [["ndcg", "nDCG@5"]],
    agentic_rare: [["ndcg", "nDCG@5"]],
    finance: [["recall", "recall@5"], ["mrr", "MRR@5"],
      ["filings_recall", "filings"], ["filingdoc_recall", "filingdoc"]],
    scholar: [["recall", "recall@10"], ["mrr", "MRR@10"],
      ["title_recall", "title"], ["body_recall", "body"],
      ["clue_recall", "clue"], ["tot_recall", "tot"]],
    legal: [["recall", "recall@5"], ["mrr", "MRR@5"],
      ["caselaw_recall", "caselaw"], ["code_recall", "code"]],
  };
  const nameOf = (e) => DISPLAY.get(e) ?? e;
  const fmt = (v) => v == null ? "–" : v.toFixed(3);

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

  const parseRows = (text) => text.split("\n").filter(Boolean).map((l) => JSON.parse(l));

  const boot = async () => {
    const holder = document.getElementById("bench-leaderboard");
    const sub = document.getElementById("bench-sub");
    const filter = document.getElementById("bench-filter");
    if (!holder) return;
    const bench = holder.dataset.bench;
    const metrics = METRICS[bench];
    const root = document.documentElement.dataset.root || ".";
    let rows = [];
    try {
      const resp = await fetch(`${root}/data/history.jsonl`, { cache: "no-store" });
      rows = resp.ok ? parseRows(await resp.text()) : [];
    } catch {
      rows = [];
    }
    const cutoff = Date.now() - 7 * 86400e3;
    const week = rows.filter((r) => r.bench === bench && !HIDDEN.has(r.engine)
      && new Date(r.ts).getTime() >= cutoff);
    const engines = [...new Set(week.map((r) => r.engine))];
    const entries = engines.map((e) => {
      const er = week.filter((r) => r.engine === e);
      return {
        e,
        vals: metrics.map(([m]) => wmean(er, m)),
        n: er.filter((r) => r[metrics[0][0]] != null && r.num_scored > 0).length,
      };
    }).filter((x) => x.vals[0] != null);
    entries.sort((a, b) => b.vals[0] - a.vals[0]);
    holder.replaceChildren();
    if (!entries.length) {
      if (sub) sub.textContent = "";
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "No scored runs in the last 7 days.";
      holder.appendChild(empty);
      return;
    }
    if (sub) {
      const runs = Math.max(...entries.map((x) => x.n));
      sub.textContent = `Query-weighted 7-day mean · ${runs} run${runs === 1 ? "" : "s"}`;
    }
    const table = document.createElement("table");
    const head = document.createElement("tr");
    head.appendChild(Object.assign(document.createElement("th"), { textContent: "engine" }));
    for (const [, label] of metrics) {
      const th = document.createElement("th");
      th.className = "num";
      th.textContent = label;
      head.appendChild(th);
    }
    table.appendChild(head);
    for (const x of entries) {
      const tr = document.createElement("tr");
      if (x.e === "ultimate") tr.classList.add("ultimate");
      if (x.e === "keenable-realtime") tr.classList.add("home");
      const name = document.createElement("td");
      name.textContent = nameOf(x.e);
      tr.appendChild(name);
      x.vals.forEach((v) => {
        const td = document.createElement("td");
        td.className = "num";
        td.textContent = fmt(v);
        tr.appendChild(td);
      });
      table.appendChild(tr);
    }
    holder.appendChild(table);
    if (filter) {
      filter.addEventListener("input", () => {
        const q = filter.value.trim().toLowerCase();
        for (const tr of table.querySelectorAll("tr")) {
          if (!tr.querySelector("td")) continue;
          tr.hidden = q && !tr.textContent.toLowerCase().includes(q);
        }
      });
    }
  };

  boot();
})();
