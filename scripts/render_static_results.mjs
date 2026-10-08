import { createServer } from "node:http";
import { readFile, writeFile } from "node:fs/promises";
import { extname, join, resolve } from "node:path";
import { chromium } from "playwright-core";

const [siteDir] = process.argv.slice(2);
const root = resolve(siteDir);
const indexPath = join(root, "index.html");

const TABLE_HOLDERS = ["standings", "lb-overall", "lb-scholar", "lb-fresh", "lb-company",
                       "lb-rare", "lb-legal", "quality-price", "prices-table", "latency-dumbbell"];
const TEXT_HOLDERS = ["updated", "lb-overall-sub", "lb-scholar-sub", "lb-fresh-sub",
                      "lb-company-sub", "lb-rare-sub", "lb-legal-sub", "quality-price-sub",
                      "prices-sub"];
const MARKDOWN_LINK =
  '<link rel="alternate" type="text/markdown" href="results.md" title="NEEDLE results as Markdown">';

const MIME = { ".html": "text/html", ".json": "application/json",
               ".jsonl": "application/x-ndjson", ".png": "image/png" };

const server = createServer(async (req, res) => {
  const path = decodeURIComponent(req.url.split("?")[0]);
  const file = join(root, path === "/" ? "index.html" : path.slice(1));
  try {
    const data = await readFile(file);
    res.writeHead(200, { "content-type": MIME[extname(file)] ?? "application/octet-stream" });
    res.end(data);
  } catch {
    res.writeHead(404);
    res.end();
  }
});

const escapeHtml = (s) => String(s).replace(/\s+/g, " ").trim()
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

const tableHtml = ([head, ...body]) => {
  const cells = (row, tag) => row.map((c) => `<${tag}>${escapeHtml(c)}</${tag}>`).join("");
  const bodyRows = body.map((row) => `<tr>${cells(row, "td")}</tr>`).join("");
  return `<table><thead><tr>${cells(head, "th")}</tr></thead><tbody>${bodyRows}</tbody></table>`;
};

const fillEmptyElement = (doc, id, inner) => {
  const pattern = new RegExp(`(<(div|span)\\b[^>]*\\bid="${id}"[^>]*>)(</\\2>)`, "g");
  const matches = doc.match(pattern) ?? [];
  if (matches.length !== 1) throw new Error(`expected one empty #${id}, found ${matches.length}`);
  return doc.replace(pattern, (_, open, _tag, close) => `${open}${inner}${close}`);
};

const readSnapshot = (page) => page.evaluate(({ tableHolders, textHolders }) => {
  const rowsFor = (id) => {
    const card = document.getElementById(id)?.closest(".lb-panel, .card");
    return card ? cardRows(card) : null;
  };
  return {
    tables: Object.fromEntries(tableHolders.map((id) => [id, rowsFor(id)])),
    texts: Object.fromEntries(textHolders.map(
      (id) => [id, document.getElementById(id)?.textContent.trim() ?? ""])),
    verticals: Object.fromEntries([...document.querySelectorAll("span.vert[data-vert]")]
      .map((s) => [s.dataset.vert, s.textContent.trim()])),
    markdown: buildMarkdown(),
  };
}, { tableHolders: TABLE_HOLDERS, textHolders: TEXT_HOLDERS });

let browser;
try {
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  browser = await chromium.launch(
    process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH }
                            : { channel: "chrome" });
  const page = await browser.newPage();
  await page.goto(`http://127.0.0.1:${server.address().port}/`, { waitUntil: "load" });
  await page.waitForFunction(() => document.getElementById("updated").textContent.trim()
    && cardRows(document.getElementById("card-standings")), null, { timeout: 60000 });
  await page.waitForFunction((ids) => ids.every((id) => {
    const card = document.getElementById(id)?.closest(".lb-panel, .card");
    return card && cardRows(card);
  }), TABLE_HOLDERS, { timeout: 30000 }).catch(() => {});
  const snapshot = await readSnapshot(page);

  let doc = await readFile(indexPath, "utf8");
  let tables = 0;
  for (const [id, rows] of Object.entries(snapshot.tables)) {
    if (!rows) {
      console.error(`no rows for #${id}, left empty`);
      continue;
    }
    doc = fillEmptyElement(doc, id, tableHtml(rows));
    tables++;
  }
  for (const [id, text] of Object.entries(snapshot.texts)) {
    if (text) doc = fillEmptyElement(doc, id, escapeHtml(text));
  }
  doc = doc.replace(/<span class="vert" data-vert="([a-z_]+)"><\/span>/g, (empty, key) =>
    snapshot.verticals[key]
      ? `<span class="vert" data-vert="${key}">${escapeHtml(snapshot.verticals[key])}</span>`
      : empty);
  doc = doc.replace("</head>", `${MARKDOWN_LINK}\n</head>`);
  await writeFile(join(root, "results.md"), snapshot.markdown);
  await writeFile(indexPath, doc);
  console.log(`prerendered ${tables}/${TABLE_HOLDERS.length} tables; wrote results.md`);
} catch (e) {
  console.error(`static results failed, index.html left as is: ${e.message.split("\n")[0]}`);
} finally {
  await browser?.close();
  server.close();
}
