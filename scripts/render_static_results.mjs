import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { withDashboard } from "./dashboard_page.mjs";
import { resultsFiles, sitemapXml } from "./results_page.mjs";

const [rootArg, now] = process.argv.slice(2);
const root = resolve(rootArg);
const indexPath = join(root, "index.html");
const resultsTemplate = new URL("../dashboard/results.html", import.meta.url);
const historyPosts = new URL("../dashboard/history_posts.json", import.meta.url);
const HISTORY_FILE = /^needle-[a-z]+-(\d{4}-\d{2})\.([a-z]+)$/;
const MARKDOWN_LINK =
  '<link rel="alternate" type="text/markdown" href="results.md" title="NEEDLE results as Markdown">';
const RESULTS_LINK = ' <a href="results/">Results table</a>.';

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

  return {
    html,
    missing,
    verticals: Object.fromEntries(VERTICALS),
    summary: document.getElementById("card-standings")._summaryData?.() ?? null,
    lastRun: new Date(history[history.length - 1].ts).toISOString(),
    pricesAsOf: PRICES_ASOF,
    base: document.querySelector('meta[property="og:url"]').content,
    families: Object.fromEntries(ENGINE_FAMILY),
    logo: document.querySelector(".brand svg")?.outerHTML ?? "",
  };
});

async function readHistory() {
  const months = new Map();
  for (const name of await readdir(join(root, "history")).catch(() => [])) {
    const m = name.match(HISTORY_FILE);
    if (!m) continue;
    if (!months.has(m[1])) months.set(m[1], {});
    months.get(m[1])[m[2]] = name;
  }
  return [...months].map(([month, files]) => ({ month, files }));
}

async function renderShareImage(page, { html, size }) {
  const tab = await page.context().browser().newPage({ viewport: size, deviceScaleFactor: 1 });
  try {
    await tab.setContent(html, { waitUntil: "load" });
    await tab.evaluate(() => document.fonts.ready);
    const png = await tab.screenshot({ type: "png" });
    const webp = await tab.evaluate(async (src) => {
      const img = new Image();
      img.src = src;
      await img.decode();
      const canvas = document.createElement("canvas");
      canvas.width = img.width;
      canvas.height = img.height;
      canvas.getContext("2d").drawImage(img, 0, 0);
      return canvas.toDataURL("image/webp", 1);
    }, `data:image/png;base64,${png.toString("base64")}`);
    if (!webp.startsWith("data:image/webp")) throw new Error("this browser cannot encode WebP");
    return { png, webp: Buffer.from(webp.split(",")[1], "base64") };
  } finally {
    await tab.close();
  }
}

async function renderPdf(page, html) {
  await page.emulateMedia({ media: "print", colorScheme: "light" });
  await page.setContent(html, { waitUntil: "load" });
  return page.pdf({ format: "A4", landscape: true, printBackground: true,
                    margin: { top: "12mm", bottom: "12mm", left: "10mm", right: "10mm" } });
}

try {
  await withDashboard(root, { now }, async (page) => {
    await page.waitForFunction(
      () => document.getElementById("updated").textContent.trim(), null, { timeout: 60000 });
    const snapshot = await readSnapshot(page);
    Object.assign(snapshot, {
      history: await readHistory(),
      posts: JSON.parse(await readFile(historyPosts, "utf8")),
    });
    const results = snapshot.summary && resultsFiles(await readFile(resultsTemplate, "utf8"), snapshot);
    const markdown = await page.evaluate((parts) => buildMarkdown(parts), results?.markdown ?? {});
    const share = results && await renderShareImage(page, results.share);
    const pdf = results && await renderPdf(page, results.page);

    let doc = await readFile(indexPath, "utf8");
    for (const [id, inner] of Object.entries({ ...snapshot.html, "results-link": results ? RESULTS_LINK : "" })) {
      doc = fillEmptyElement(doc, id, inner);
    }
    doc = doc.replace(/<span class="vert" data-vert="([a-z_]+)"><\/span>/g, (_, key) =>
      `<span class="vert" data-vert="${key}">${snapshot.verticals[key] ?? key}</span>`);
    doc = doc.replace("</head>", `${MARKDOWN_LINK}\n</head>`);

    if (results) {
      await mkdir(join(root, "results"), { recursive: true });
      await writeFile(join(root, "results", "index.html"), results.page);
      await writeFile(join(root, "results.csv"), results.csv);
      await writeFile(join(root, "results.json"), results.json);
      await writeFile(join(root, "results.pdf"), pdf);
      await mkdir(dirname(join(root, results.share.path)), { recursive: true });
      await writeFile(join(root, `${results.share.path}.png`), share.png);
      await writeFile(join(root, `${results.share.path}.webp`), share.webp);
    }
    await writeFile(join(root, "results.md"), markdown);
    await writeFile(join(root, "sitemap.xml"),
      sitemapXml([snapshot.base, ...(results ? [`${snapshot.base}results/`] : [])], snapshot.lastRun));
    await writeFile(indexPath, doc);
    for (const id of snapshot.missing) console.error(`no rows for #${id}, left empty`);
    if (!results) warn("no standings in the last 7 days, results/ not written");
    console.log(`filled ${Object.keys(snapshot.html).length} elements; wrote `
      + (results ? `results/ (${snapshot.summary.engines.length} engines, ${snapshot.history.length} `
                   + `history months), csv, json, pdf, ${results.share.path}.png/.webp`
                 : "no results/ (no standings)")
      + ", results.md and sitemap.xml");
  });
} catch (e) {
  warn(`static results failed, index.html left as is: ${e.message.split("\n")[0]}`);
}
