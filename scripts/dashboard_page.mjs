import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, resolve } from "node:path";
import { chromium } from "playwright-core";

const MIME = { ".html": "text/html", ".json": "application/json",
               ".jsonl": "application/x-ndjson", ".png": "image/png" };

function serveSite(root) {
  return createServer(async (req, res) => {
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
}

export async function openDashboard(siteDir, pageOptions) {
  const server = serveSite(resolve(siteDir));
  let browser;
  const close = async () => {
    await browser?.close();
    server.close();
  };
  try {
    await new Promise((r) => server.listen(0, "127.0.0.1", r));
    browser = await chromium.launch(
      process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH }
                              : { channel: "chrome" });
    const page = await browser.newPage(pageOptions);
    await page.goto(`http://127.0.0.1:${server.address().port}/`, { waitUntil: "load" });
    return { page, close };
  } catch (e) {
    await close();
    throw e;
  }
}
