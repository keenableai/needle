import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { withDashboard } from "./dashboard_page.mjs";

const root = resolve(process.argv[2]);
const indexPath = join(root, "index.html");
const resultsTemplate = new URL("../dashboard/results.html", import.meta.url);
const MARKDOWN_LINK =
  '<link rel="alternate" type="text/markdown" href="results.md" title="NEEDLE results as Markdown">';
const RESULTS_LINK =
  ' <a href="results/">Results table</a> · <a href="results.md">all tables as Markdown</a>.';
const MARKDOWN_ONLY_LINK = ' <a href="results.md">All tables as Markdown</a>.';

const warn = (message) =>
  console.log(`::warning title=Static results::${message.replace(/%/g, "%25")}`);

const fillEmptyElement = (doc, id, inner) => {
  let found = 0;
  const filled = doc.replace(new RegExp(`<(div|span)\\b[^>]*\\bid="${id}"[^>]*>(?=</\\1>)`, "g"),
    (open) => {
      found++;
      return open + inner;
    });
  if (found !== 1) throw new Error(`expected one empty #${id}, found ${found}`);
  return filled;
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
  const summary = document.getElementById("card-standings")._summaryRows?.();

  return {
    html,
    missing,
    verticals: Object.fromEntries(VERTICALS),
    markdown: buildMarkdown(),
    summaryTable: summary ? tableHtml(summary) : null,
    engines: summary ? summary.length - 1 : 0,
    lastRun: new Date(history[history.length - 1].ts).toISOString(),
    pricesAsOf: PRICES_ASOF,
    base: document.querySelector('meta[property="og:url"]').content,
  };
});

try {
  const snapshot = await withDashboard(root, {}, async (page) => {
    await page.waitForFunction(
      () => document.getElementById("updated").textContent.trim(), null, { timeout: 60000 });
    return readSnapshot(page);
  });

  const verticalNames = Object.values(snapshot.verticals);
  const resultsPage = snapshot.summaryTable && fillTemplate(await readFile(resultsTemplate, "utf8"), {
    BASE: snapshot.base,
    TABLE: snapshot.summaryTable,
    ENGINES: String(snapshot.engines),
    UPDATED: snapshot.html.updated,
    LAST_RUN: snapshot.lastRun,
    PRICES_ASOF: snapshot.pricesAsOf,
    VERTICAL_COUNT: String(verticalNames.length),
    VERTICALS: verticalNames.join(", "),
  });

  let doc = await readFile(indexPath, "utf8");
  const resultsLink = resultsPage ? RESULTS_LINK : MARKDOWN_ONLY_LINK;
  for (const [id, inner] of Object.entries({ ...snapshot.html, "results-link": resultsLink })) {
    doc = fillEmptyElement(doc, id, inner);
  }
  doc = doc.replace(/<span class="vert" data-vert="([a-z_]+)"><\/span>/g, (_, key) =>
    `<span class="vert" data-vert="${key}">${snapshot.verticals[key] ?? key}</span>`);
  doc = doc.replace("</head>", `${MARKDOWN_LINK}\n</head>`);

  if (resultsPage) {
    await mkdir(join(root, "results"), { recursive: true });
    await writeFile(join(root, "results", "index.html"), resultsPage);
  }
  await writeFile(join(root, "results.md"), snapshot.markdown);
  await writeFile(indexPath, doc);
  for (const id of snapshot.missing) console.error(`no rows for #${id}, left empty`);
  if (!resultsPage) warn("no standings in the last 7 days, results/ not written");
  console.log(`filled ${Object.keys(snapshot.html).length} elements; wrote `
    + (resultsPage ? `results/ (${snapshot.engines} engines)` : "no results/ (no standings)")
    + " and results.md");
} catch (e) {
  warn(`static results failed, index.html left as is: ${e.message.split("\n")[0]}`);
}
