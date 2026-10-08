import { readFile, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { openDashboard } from "./dashboard_page.mjs";

const root = resolve(process.argv[2]);
const indexPath = join(root, "index.html");
const MARKDOWN_LINK =
  '<link rel="alternate" type="text/markdown" href="results.md" title="NEEDLE results as Markdown">';

const fillEmptyElement = (doc, id, inner) => {
  const pattern = new RegExp(`(<(div|span)\\b[^>]*\\bid="${id}"[^>]*>)(</\\2>)`, "g");
  const matches = doc.match(pattern) ?? [];
  if (matches.length !== 1) throw new Error(`expected one empty #${id}, found ${matches.length}`);
  return doc.replace(pattern, (_, open, _tag, close) => `${open}${inner}${close}`);
};

const readSnapshot = (page) => page.evaluate(() => {
  const tableRow = (cells, tag) => {
    const tr = el("tr");
    tr.append(...cells.map((c) => el(tag, {}, c)));
    return tr;
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
    const table = el("table");
    table.createTHead().append(tableRow(rows[0], "th"));
    table.createTBody().append(...rows.slice(1).map((r) => tableRow(r, "td")));
    html[holder.id] = table.outerHTML;
    const sub = card.querySelector(".sub[id]");
    if (sub?.textContent.trim()) html[sub.id] = sub.innerHTML;
  }
  return { html, missing, verticals: Object.fromEntries(VERTICALS), markdown: buildMarkdown() };
});

let dashboard;
try {
  dashboard = await openDashboard(root);
  await dashboard.page.waitForFunction(
    () => document.getElementById("updated").textContent.trim(), null, { timeout: 60000 });
  const snapshot = await readSnapshot(dashboard.page);

  let doc = await readFile(indexPath, "utf8");
  for (const [id, inner] of Object.entries(snapshot.html)) doc = fillEmptyElement(doc, id, inner);
  doc = doc.replace(/<span class="vert" data-vert="([a-z_]+)"><\/span>/g, (empty, key) =>
    snapshot.verticals[key] ? `<span class="vert" data-vert="${key}">${snapshot.verticals[key]}</span>`
                            : empty);
  doc = doc.replace("</head>", `${MARKDOWN_LINK}\n</head>`);
  await writeFile(join(root, "results.md"), snapshot.markdown);
  await writeFile(indexPath, doc);
  for (const id of snapshot.missing) console.error(`no rows for #${id}, left empty`);
  console.log(`prerendered ${Object.keys(snapshot.html).length} holders; wrote results.md`);
} catch (e) {
  console.error(`static results failed, index.html left as is: ${e.message.split("\n")[0]}`);
} finally {
  await dashboard?.close();
}
