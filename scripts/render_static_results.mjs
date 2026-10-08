import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { openDashboard } from "./dashboard_page.mjs";

const root = resolve(process.argv[2]);
const indexPath = join(root, "index.html");
const resultsTemplate = new URL("../dashboard/results.html", import.meta.url);
const MARKDOWN_LINK =
  '<link rel="alternate" type="text/markdown" href="results.md" title="NEEDLE results as Markdown">';
const RESULTS_LINK =
  ' <a href="results/">Results table</a> · <a href="results.md">all tables as Markdown</a>.';

const fillEmptyElement = (doc, id, inner) => {
  const pattern = new RegExp(`(<(div|span)\\b[^>]*\\bid="${id}"[^>]*>)(</\\2>)`, "g");
  const matches = doc.match(pattern) ?? [];
  if (matches.length !== 1) throw new Error(`expected one empty #${id}, found ${matches.length}`);
  return doc.replace(pattern, (_, open, _tag, close) => `${open}${inner}${close}`);
};

const fillTemplate = (template, values) =>
  template.replace(/\{\{([A-Z_]+)\}\}/g, (slot, key) => {
    if (!(key in values)) throw new Error(`no value for ${slot}`);
    return values[key];
  });

const readSnapshot = (page) => page.evaluate(() => {
  const tableRow = (cells, tag) => {
    const tr = el("tr");
    tr.append(...cells.map((c) => el(tag, {}, c)));
    return tr;
  };
  const tableHtml = ([head, ...body]) => {
    const table = el("table");
    table.createTHead().append(tableRow(head, "th"));
    table.createTBody().append(...body.map((r) => tableRow(r, "td")));
    return table.outerHTML;
  };
  const rowsByEngine = (cardId) =>
    new Map((cardRows(document.getElementById(cardId)) ?? []).slice(1).map((r) => [r[0], r]));

  const html = { updated: document.getElementById("updated").innerHTML };
  const missing = [];
  for (const holder of document.querySelectorAll("[data-static]")) {
    const card = holder.closest(".lb-panel, .card");
    const rows = cardRows(card);
    if (!rows) {
      missing.push(holder.id);
      continue;
    }
    html[holder.id] = tableHtml(rows);
    const sub = card.querySelector(".sub[id]");
    if (sub?.textContent.trim()) html[sub.id] = sub.innerHTML;
  }

  const [head, _ultimate, _gap, ...engines] = cardRows(document.getElementById("card-standings"));
  const prices = rowsByEngine("card-prices");
  const latency = rowsByEngine("card-latency-dumbbell");
  const summary = [
    [...head, "$ / 1k queries", "p50 latency", "p95 latency"],
    ...engines.map((r) => [...r, prices.get(r[0])?.[1] ?? "–",
                           latency.get(r[0])?.[1] ?? "–", latency.get(r[0])?.[2] ?? "–"]),
  ];

  return {
    html,
    missing,
    verticals: Object.fromEntries(VERTICALS),
    markdown: buildMarkdown(),
    results: {
      table: tableHtml(summary),
      engines: engines.length,
      lastRun: new Date(history[history.length - 1].ts).toISOString(),
      pricesAsOf: PRICES_ASOF,
    },
  };
});

const datasetJsonLd = ({ lastRun }) => JSON.stringify({
  "@context": "https://schema.org",
  "@type": "Dataset",
  name: "NEEDLE web search API benchmark results",
  description: "Quality, price per 1,000 queries, and latency of web search APIs for AI agents, "
    + "measured each day on news, finance, scholar, rare-word, and legal queries.",
  url: "https://keenableai.github.io/needle/results/",
  dateModified: lastRun,
  license: "https://opensource.org/license/mit",
  creator: { "@type": "Organization", name: "Keenable", url: "https://keenable.ai" },
  isAccessibleForFree: true,
  distribution: [
    { "@type": "DataDownload", encodingFormat: "text/markdown",
      contentUrl: "https://keenableai.github.io/needle/results.md" },
    { "@type": "DataDownload", encodingFormat: "application/json",
      contentUrl: "https://huggingface.co/datasets/keenable-ai/needle-results" },
  ],
}).replace(/</g, "\\u003c");

let dashboard;
try {
  dashboard = await openDashboard(root);
  await dashboard.page.waitForFunction(
    () => document.getElementById("updated").textContent.trim(), null, { timeout: 60000 });
  const snapshot = await readSnapshot(dashboard.page);

  const resultsPage = fillTemplate(await readFile(resultsTemplate, "utf8"), {
    TABLE: snapshot.results.table,
    ENGINES: String(snapshot.results.engines),
    UPDATED: snapshot.html.updated,
    PRICES_ASOF: snapshot.results.pricesAsOf,
    JSONLD: datasetJsonLd(snapshot.results),
  });

  let doc = await readFile(indexPath, "utf8");
  for (const [id, inner] of Object.entries(snapshot.html)) doc = fillEmptyElement(doc, id, inner);
  doc = fillEmptyElement(doc, "results-link", RESULTS_LINK);
  doc = doc.replace(/<span class="vert" data-vert="([a-z_]+)"><\/span>/g, (empty, key) =>
    snapshot.verticals[key] ? `<span class="vert" data-vert="${key}">${snapshot.verticals[key]}</span>`
                            : empty);
  doc = doc.replace("</head>", `${MARKDOWN_LINK}\n</head>`);

  await mkdir(join(root, "results"), { recursive: true });
  await writeFile(join(root, "results", "index.html"), resultsPage);
  await writeFile(join(root, "results.md"), snapshot.markdown);
  await writeFile(indexPath, doc);
  for (const id of snapshot.missing) console.error(`no rows for #${id}, left empty`);
  console.log(`prerendered ${Object.keys(snapshot.html).length} holders; `
    + `wrote results/ (${snapshot.results.engines} engines) and results.md`);
} catch (e) {
  console.error(`static results failed, index.html left as is: ${e.message.split("\n")[0]}`);
} finally {
  await dashboard?.close();
}
