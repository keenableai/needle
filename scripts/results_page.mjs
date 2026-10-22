const AUTHORS = [["Andrey", "Styskin"], ["Matthias", "Petri"], ["Ilya", "Gusev"]];
const DOI = "10.5281/zenodo.22095155";
const LICENSE = "https://opensource.org/license/mit";
const REPO = "https://github.com/keenableai/needle";
const HF_DATASET = "https://huggingface.co/datasets/keenable-ai/needle-results";
const DATASET_NAME = "NEEDLE: web search API benchmark results";
const ORGANIZATION = {
  "@type": "Organization",
  "@id": "https://keenable.ai/#organization",
  name: "Keenable",
  url: "https://keenable.ai/",
  sameAs: ["https://github.com/keenableai", "https://huggingface.co/keenable-ai"],
};
const DOWNLOADS = [["results.csv", "text/csv"], ["results.json", "application/json"],
  ["results.md", "text/markdown"], ["results.pdf", "application/pdf"]];
const TITLE_RIVALS = ["exa", "parallel", "tavily", "brave"];
const PROSE_NAMES = new Map([
  ["exa", "Exa"], ["exa-instant", "Exa Instant"],
  ["exa-lite", "Exa Lite"], ["brave", "Brave"],
  ["brave-llmcontext", "Brave LLM Context"], ["parallel", "Parallel"],
  ["parallel-turbo", "Parallel Turbo"], ["perplexity", "Perplexity"],
  ["perplexity-fast", "Perplexity Fast"], ["tavily", "Tavily"], ["linkup", "Linkup"],
  ["you", "You.com"], ["firecrawl", "Firecrawl"], ["tinyfish", "TinyFish"], ["kagi", "Kagi"],
  ["jina", "Jina"], ["deepseek", "DeepSeek"], ["octen", "Octen"], ["claude-search", "Claude web search"],
  ["chatgpt-search", "ChatGPT search"],
]);
const NUMBER_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];
const ORDINAL_WORDS = ["zeroth", "first", "second", "third", "fourth", "fifth", "sixth", "seventh",
  "eighth", "ninth", "tenth"];

const utc = (options) => new Intl.DateTimeFormat("en-US", { timeZone: "UTC", ...options });
const DAY = utc({ month: "short", day: "numeric", year: "numeric" });
const DAY_TIME = utc({ month: "short", day: "numeric", year: "numeric", hour: "2-digit",
  minute: "2-digit", hourCycle: "h23" });
const SHORT_TIME = utc({ month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  hourCycle: "h23" });
const MONTH = utc({ month: "long", year: "numeric" });

const pct = (v) => `${Math.round(v * 100)}%`;
const round = (v, digits) => v == null ? null : Number(v.toFixed(digits));
const escapeHtml = (s) => String(s).replace(/[&<>"]/g, (c) => `&#${c.charCodeAt(0)};`);
const listText = (items) =>
  items.length > 1 ? `${items.slice(0, -1).join(", ")} and ${items.at(-1)}` : items.join("");
const proseName = (x) => PROSE_NAMES.get(x.engine) ?? x.name;
const ordinal = (n) => {
  const tens = n % 100;
  return `${n}${tens >= 11 && tens <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] ?? "th"}`;
};
const numberWord = (n) => NUMBER_WORDS[n] ?? String(n);
const ordinalWord = (n) => ORDINAL_WORDS[n] ?? ordinal(n);

function race(label, engines, scoreOf) {
  const list = engines.map((x) => ({ x, ...scoreOf(x) }))
    .filter((s) => s.score != null)
    .sort((a, b) => b.score - a.score);
  if (!list.length) return null;
  const [leader, runnerUp] = list;
  const home = list.find((s) => s.x.home);
  return {
    label, list, leader, runnerUp, home,
    close: Boolean(leader.ci && runnerUp?.ci && leader.ci[0] <= runnerUp.ci[1]),
    homeRank: home && 1 + list.filter((s) => s.score > home.score && pct(s.score) !== pct(home.score)).length,
    tiedWithHome: home ? list.filter((s) => s !== home && pct(s.score) === pct(home.score)) : [],
  };
}

function runnersUp(list) {
  const shown = [];
  for (const s of list.slice(1)) {
    if (shown.length >= 3 && pct(s.score) !== pct(shown.at(-1).score)) break;
    shown.push(s);
  }
  const groups = [];
  for (const s of shown) {
    const last = groups.at(-1);
    if (last && pct(last[0].score) === pct(s.score)) last.push(s);
    else groups.push([s]);
  }
  return groups.map((g) => `${listText(g.map((s) => proseName(s.x)))} ${pct(g[0].score)}`).join(", ");
}

const homePlaceText = (r) => `${r.tiedWithHome.length ? "ties for" : "is"} ${ordinalWord(r.homeRank)}`;
const overlapNote = (r) => r.close ? `; ${proseName(r.runnerUp.x)} ${pct(r.runnerUp.score)}, intervals overlap` : "";

function leadText({ summary, overall, verticals, lastRun, cellOf }) {
  const leader = overall.leader.x;
  const sentences = [`As of ${DAY.format(lastRun)}, NEEDLE compares ${summary.engines.length} web search APIs `
    + `on the same queries in ${numberWord(verticals.length)} verticals.`];
  const led = verticals.filter((r) => r.leader.x === leader)
    .map((r) => `${r.label} (${pct(r.leader.score)}${overlapNote(r)})`);
  const runners = runnersUp(overall.list);
  sentences.push(`${proseName(leader)} leads overall with ${pct(overall.leader.score)} of the ceiling`
    + `${runners ? ` (${runners}${overall.close ? ", intervals overlap" : ""})` : ""}`
    + `${led.length ? `, and leads ${listText(led)}` : ""}.`);
  const home = overall.home;
  if (home && home.x !== leader) {
    sentences.push(`${proseName(home.x)} ${homePlaceText(overall)} overall with ${pct(home.score)}.`);
  }
  const others = verticals.filter((r) => r.leader.x !== leader).map((r) => {
    const where = r.home && r.home !== r.leader
      ? `, where ${proseName(r.home.x)} ${homePlaceText(r)} (${pct(r.home.score)})` : "";
    return `${proseName(r.leader.x)} leads ${r.label} (${pct(r.leader.score)}${overlapNote(r)})${where}`;
  });
  if (others.length) sentences.push(`${others.join("; ")}.`);
  if (home?.x.p50 != null) {
    const fastest = Math.min(...summary.engines.map((x) => x.p50 ?? Infinity));
    const latency = cellOf(home.x, "p50 latency");
    const price = home.x.price ? `, at ${cellOf(home.x, "$ / 1k queries")} per 1,000 queries` : "";
    sentences.push(`${proseName(home.x)} has `
      + `${home.x.p50 === fastest ? `the lowest median latency, ${latency}` : `a median latency of ${latency}`}`
      + `${price}.`);
  }
  return sentences.join(" ");
}

function htmlTable({ caption, head, rows, className }) {
  const headCells = head.map((h) => `<th scope="col">${escapeHtml(h)}</th>`).join("");
  const body = rows.map(({ cells, home, bold }) => {
    const [name, ...rest] = cells;
    const tds = rest.map((c, i) => bold?.has(i + 1)
      ? `<td class="best"><strong>${escapeHtml(c)}</strong></td>`
      : `<td>${escapeHtml(c)}</td>`).join("");
    return `<tr${home ? ' class="us"' : ""}><th scope="row">${escapeHtml(name)}</th>${tds}</tr>`;
  });
  return [`<table${className ? ` class="${className}"` : ""}>`,
    `<caption>${escapeHtml(caption)}</caption>`,
    `<thead><tr>${headCells}</tr></thead>`,
    "<tbody>", ...body, "</tbody>", "</table>"].join("\n");
}

function homePlace(r) {
  if (!r.home) return "–";
  const tied = r.tiedWithHome.length ? ` (tied with ${listText(r.tiedWithHome.map((s) => s.x.name))})` : "";
  if (r.homeRank > 1) return `${ordinal(r.homeRank)}, ${pct(r.home.score)}${tied}`;
  if (tied) return `1st${tied}`;
  return r.close ? `1st (${r.runnerUp.x.name} ${pct(r.runnerUp.score)}, intervals overlap)` : "1st";
}

function leadersTable(overall, verticals) {
  const homeName = overall.home?.x.name;
  return htmlTable({
    className: "leaders",
    caption: `Best score in each vertical${homeName ? ` and ${homeName}'s place` : ""}, last 7 days`,
    head: ["Vertical", "Leader", "Score", ...(homeName ? [homeName] : [])],
    rows: [overall, ...verticals].map((r) => ({
      cells: [r.label, r.leader.x.name, pct(r.leader.score), ...(homeName ? [homePlace(r)] : [])],
    })),
  });
}

function resultsTable(summary, caption) {
  const values = (x) => [null, x.overall, null, ...x.verticals.map((v) => v?.share ?? null),
    x.price?.usd ?? null, x.p50, x.p95, x.unique];
  const better = [null, "max", null, ...summary.verticals.map(() => "max"), "min", "min", "min", "max"];
  if (better.length !== summary.header.length) {
    throw new Error(`summary has ${summary.header.length} columns, expected ${better.length}`);
  }
  const bestText = better.map((how, i) => {
    const scored = how ? summary.engines.filter((x) => values(x)[i] != null) : [];
    if (!scored.length) return null;
    const isBetter = (a, b) => how === "max" ? values(b)[i] > values(a)[i] : values(b)[i] < values(a)[i];
    return scored.reduce((a, b) => isBetter(a, b) ? b : a).cells[i];
  });
  return htmlTable({
    caption,
    head: summary.header,
    rows: summary.engines.map((x) => ({
      cells: x.cells,
      home: x.home,
      bold: new Set(x.cells.flatMap((c, i) => bestText[i] != null && c === bestText[i] ? [i] : [])),
    })),
  });
}

function citationText(pageUrl, asOfMonth) {
  const authors = AUTHORS.map(([given, family]) => `${family}, ${given[0]}.`);
  return `${authors.slice(0, -1).join(", ")}, & ${authors.at(-1)} (2026). NEEDLE: A live open-source `
    + `search benchmark for AI agents (results as of ${asOfMonth}). Keenable. ${pageUrl} , https://doi.org/${DOI}`;
}

function bibtex(pageUrl, asOfMonth) {
  return ["@misc{needle2026,",
    `  author = {${AUTHORS.map(([given, family]) => `${family}, ${given}`).join(" and ")}},`,
    "  title  = {{NEEDLE}: A Live Open-Source Search Benchmark for {AI} Agents},",
    "  year   = {2026},",
    `  url    = {${pageUrl}},`,
    `  doi    = {${DOI}},`,
    `  note   = {Live benchmark; results as of ${asOfMonth}}`,
    "}"].join("\n");
}

function jsonLd({ summary, verticalNames, pageUrl, base, lastRun, citation }) {
  const percentOfCeiling = (name, description) =>
    ({ "@type": "PropertyValue", name, ...(description && { description }), unitText: "percent of ceiling" });
  const dataset = {
    "@type": "Dataset",
    "@id": `${pageUrl}#dataset`,
    name: DATASET_NAME,
    description: `Quality, price per 1,000 queries, latency and result uniqueness of ${summary.engines.length} `
      + `web search APIs for AI agents, measured in ${verticalNames.length} verticals: `
      + `${verticalNames.join(", ")}. New queries come from public sources every hour for News and every day `
      + "for the other verticals.",
    url: pageUrl,
    sameAs: [HF_DATASET],
    dateModified: lastRun.toISOString(),
    temporalCoverage: `${summary.window[0].slice(0, 10)}/${summary.window[1].slice(0, 10)}`,
    license: LICENSE,
    isAccessibleForFree: true,
    creator: { "@id": ORGANIZATION["@id"] },
    author: AUTHORS.map(([given, family]) => ({ "@type": "Person", name: `${given} ${family}` })),
    isBasedOn: {
      "@type": "SoftwareSourceCode",
      name: "NEEDLE benchmark",
      codeRepository: REPO,
      programmingLanguage: "Python",
      license: LICENSE,
      identifier: `https://doi.org/${DOI}`,
    },
    measurementTechnique: "Blind LLM judge for News and AgenticRare; known-item matching for Scholar and "
      + "Legal; known-answer matching with an LLM check for Finance. Scores are shares of a pooled ceiling engine.",
    variableMeasured: [
      percentOfCeiling("Overall score", "Mean share of the ceiling across verticals, last 7 days"),
      ...verticalNames.map((name) => percentOfCeiling(`${name} score`)),
      { "@type": "PropertyValue", name: "Price per 1,000 queries", unitText: "USD" },
      { "@type": "PropertyValue", name: "Latency p50", unitText: "milliseconds" },
      { "@type": "PropertyValue", name: "Latency p95", unitText: "milliseconds" },
      { "@type": "PropertyValue", name: "Unique relevant URLs", unitText: "percent of returned URLs" },
    ],
    distribution: DOWNLOADS.map(([file, encodingFormat]) =>
      ({ "@type": "DataDownload", encodingFormat, contentUrl: `${base}${file}` })),
    citation,
  };
  const graph = { "@context": "https://schema.org", "@graph": [dataset, ORGANIZATION] };
  return JSON.stringify(graph, null, 1).replace(/</g, "\\u003c");
}

function resultsCsv(summary) {
  const head = ["engine", "engine_id", "overall", "overall_ci_low", "overall_ci_high",
    ...summary.verticals.map((v) => v.key), "price_usd_per_1k", "price_plan",
    "p50_latency_ms", "p95_latency_ms", "unique_urls_share"];
  const rows = summary.engines.map((x) => [x.name, x.engine, round(x.overall, 4),
    round(x.ci?.[0], 4), round(x.ci?.[1], 4), ...x.verticals.map((v) => round(v?.share, 4)),
    x.price?.usd, x.price?.plan, round(x.p50, 0), round(x.p95, 0), round(x.unique, 4)]);
  const field = (v) => v == null ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v);
  return `${[head, ...rows].map((r) => r.map(field).join(",")).join("\n")}\n`;
}

function resultsJson({ summary, names, pageUrl, lastRun, pricesAsOf, citation }) {
  const roundAll = (xs, digits) => xs?.map((v) => round(v, digits)) ?? null;
  return `${JSON.stringify({
    name: DATASET_NAME,
    url: pageUrl,
    updated: lastRun.toISOString(),
    window: { start: summary.window[0], end: summary.window[1] },
    score: "Share of the ceiling: a synthetic engine that pools every engine's results per query. "
      + "100% is the best result list the whole field found together.",
    prices_as_of: pricesAsOf,
    verticals: summary.verticals.map((v) => ({ id: v.key, name: names[v.key] ?? v.key, runs: v.runs, last_run: v.lastRun })),
    engines: summary.engines.map((x) => ({
      engine: x.name,
      engine_id: x.engine,
      overall: round(x.overall, 4),
      overall_ci: roundAll(x.ci, 4),
      verticals: Object.fromEntries(summary.verticals.map((v, i) => [v.key,
        x.verticals[i] && { share: round(x.verticals[i].share, 4), ci: roundAll(x.verticals[i].ci, 4) }])),
      price_usd_per_1k: x.price?.usd ?? null,
      price_plan: x.price?.plan ?? null,
      latency_ms: { p50: round(x.p50, 0), p95: round(x.p95, 0) },
      unique_urls_share: round(x.unique, 4),
    })),
    license: LICENSE,
    citation,
  }, null, 2)}\n`;
}

export function resultsFiles(template, snapshot) {
  const { summary, verticals: names, base, pricesAsOf } = snapshot;
  const lastRun = new Date(snapshot.lastRun);
  const pageUrl = `${base}results/`;
  const cellOf = (x, head) => x.cells[summary.header.indexOf(head)];
  const overall = race("Overall", summary.engines, (x) => ({ score: x.overall, ci: x.ci }));
  const verticals = summary.verticals
    .map((v, i) => race(names[v.key] ?? v.key, summary.engines,
      (x) => ({ score: x.verticals[i]?.share ?? null, ci: x.verticals[i]?.ci ?? null })))
    .filter(Boolean);
  const verticalNames = summary.verticals.map((v) => names[v.key] ?? v.key);
  const lead = leadText({ summary, overall, verticals, lastRun, cellOf });
  const asOfMonth = MONTH.format(lastRun);
  const citation = citationText(pageUrl, asOfMonth);
  const home = summary.engines.find((x) => x.home);
  const rivals = TITLE_RIVALS.map((e) => summary.engines.find((x) => x.engine === e)).filter(Boolean).map(proseName);
  const engines = summary.engines.length;
  const updated = `${DAY_TIME.format(lastRun)} UTC`;
  const runs = summary.verticals.map((v) => `${names[v.key] ?? v.key} ${v.runs}`
    + `${v.lastRun ? ` (latest ${SHORT_TIME.format(new Date(v.lastRun))} UTC)` : ""}`);
  const values = {
    TITLE: home && rivals.length
      ? `Web Search API Benchmark ${lastRun.getUTCFullYear()}: ${proseName(home)} vs ${rivals.slice(0, 3).join(", ")}`
      : `Web Search API Benchmark ${lastRun.getUTCFullYear()}: ${engines} engines compared`,
    H1: home && rivals.length
      ? `Web search API benchmark results: ${proseName(home)} vs ${rivals.join(", ")} and ${engines - 1 - rivals.length} more`
      : `Web search API benchmark results: ${engines} engines compared`,
    DESCRIPTION: `NEEDLE benchmark results: ${engines} web search APIs for AI agents compared on quality in `
      + `${verticals.length} verticals, price per 1,000 queries and latency. Updated ${DAY.format(lastRun)}.`,
    OG_DESCRIPTION: `Quality in ${verticals.length} verticals, price per 1,000 queries and latency. `
      + `Updated ${DAY.format(lastRun)}.`,
    ENGINES: String(engines),
    VERTICALS: verticalNames.join(", "),
    AUTHORS: listText(AUTHORS.map((a) => a.join(" "))),
    LAST_RUN: lastRun.toISOString(),
    UPDATED: updated,
    LEAD: lead,
    RUNS: `Runs behind the 7-day means: ${runs.join(", ")}.`,
    PRICES_ASOF: pricesAsOf,
    CITATION: citation,
    BIBTEX: bibtex(pageUrl, asOfMonth),
    DOI,
  };
  const html = Object.fromEntries(Object.entries(values).map(([k, v]) => [k, escapeHtml(v)]));
  Object.assign(html, {
    BASE: escapeHtml(base),
    PAGE_URL: escapeHtml(pageUrl),
    JSON_LD: jsonLd({ summary, verticalNames, pageUrl, base, lastRun, citation }),
    LEADERS_TABLE: leadersTable(overall, verticals),
    TABLE: resultsTable(summary, `NEEDLE web search API benchmark, last 7 days to ${updated}: share of the `
      + `ceiling by vertical, price, latency and result uniqueness for ${engines} engines. The best value in `
      + "each column is in bold."),
  });
  const page = template.replace(/\{\{([A-Z0-9_]+)\}\}/g, (slot, key) => {
    if (!(key in html)) throw new Error(`no value for ${slot}`);
    return html[key];
  });
  return {
    page,
    lead,
    csv: resultsCsv(summary),
    json: resultsJson({ summary, names, pageUrl, lastRun, pricesAsOf, citation }),
  };
}
