import { createServer } from "node:http";
import { mkdirSync, writeFileSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { extname, join, resolve } from "node:path";
import { chromium } from "playwright-core";

const [siteDir, outSub] = process.argv.slice(2);
const root = resolve(siteDir);
const outDir = join(root, outSub);

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

try {
  mkdirSync(outDir, { recursive: true });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));

  const browser = await chromium.launch(
    process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH }
                            : { channel: "chrome" });
  const page = await browser.newPage({ viewport: { width: 1200, height: 900 },
                                       deviceScaleFactor: 2 });
  await page.goto(`http://127.0.0.1:${server.address().port}/`, { waitUntil: "load" });
  await page.waitForSelector("#standings svg", { timeout: 20000 }).catch(() => {});
  await page.evaluate(() => document.fonts.ready);
  await page.addStyleTag({ content:
    ".lb-panel h2 { display: block !important; } .chart-tools { display: none !important; }" });
  await page.waitForTimeout(500);

  const ids = await page.evaluate(() =>
    [...document.querySelectorAll(".lb-panel[id], .card[id]")]
      .filter((el) => el.querySelector("h2"))
      .map((el) => el.id));

  let done = 0;
  for (const id of ids) {
    try {
      await page.evaluate((a) => { location.hash = ""; location.hash = a; }, `#${id}`);
      await page.waitForFunction((a) => {
        const el = document.getElementById(a);
        return el && (el.querySelector("svg") || el.textContent.trim().length > 30);
      }, id, { timeout: 4000 }).catch(() => {});
      await page.waitForTimeout(150);
      const shot = await page.locator(`#${id}`).screenshot();
      const padded = await page.evaluate(async ({ data, pad }) => {
        const img = new Image();
        img.src = data;
        await img.decode();
        const c = document.createElement("canvas");
        c.width = img.width + pad * 2;
        c.height = img.height + pad * 2;
        const ctx = c.getContext("2d");
        const bg = getComputedStyle(document.body).backgroundColor;
        ctx.fillStyle = bg === "rgba(0, 0, 0, 0)" ? "#ffffff" : bg;
        ctx.fillRect(0, 0, c.width, c.height);
        ctx.drawImage(img, pad, pad);
        return c.toDataURL("image/png");
      }, { data: `data:image/png;base64,${shot.toString("base64")}`, pad: 48 });
      writeFileSync(join(outDir, `${id}.png`),
                    Buffer.from(padded.split(",")[1], "base64"));
      done++;
    } catch (e) {
      console.error(`skip ${id}: ${e.message.split("\n")[0]}`);
    }
  }
  console.log(`rendered ${done}/${ids.length} og images`);
  await browser.close();
} catch (e) {
  console.error(`og image rendering failed, stubs will have no images: ${e.message}`);
} finally {
  server.close();
}
