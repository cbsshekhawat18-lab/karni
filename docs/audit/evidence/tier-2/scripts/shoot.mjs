// Screenshot + console/network capture. Usage: node shoot.mjs <spec.json>
// spec: { login?: {url, user, pass}, pages: [{name, url, out, waitFor?, extract?}] }
import { chromium } from "<REDACTED>/examples/eventhub/frontend/node_modules/playwright/index.mjs";
import { readFileSync, writeFileSync } from "node:fs";

const spec = JSON.parse(readFileSync(process.argv[2], "utf8"));
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1400, height: 900 } });
const page = await context.newPage();
const report = [];
let consoleMsgs = [];
let failed = [];
const apiLog = [];
page.on("request", (r) => { if (r.url().includes("/api/")) apiLog.push(`${r.method()} ${r.url().replace("http://127.0.0.1:8522","")}${r.postData() ? " body=" + r.postData().slice(0,200) : ""}`); });
page.on("response", (r) => { if (r.url().includes("/api/")) apiLog.push(`  -> ${r.status()} ${r.url().replace("http://127.0.0.1:8522","")}`); });
page.on("console", (m) => { if (["error", "warning"].includes(m.type())) consoleMsgs.push(`[${m.type()}] ${m.text().slice(0, 400)}`); });
page.on("pageerror", (e) => consoleMsgs.push(`[pageerror] ${String(e).slice(0, 400)}`));
page.on("requestfailed", (r) => failed.push(`${r.method()} ${r.url()} -> ${r.failure()?.errorText}`));
page.on("response", (r) => { if (r.status() >= 400) failed.push(`${r.request().method()} ${r.url()} -> HTTP ${r.status()}`); });

if (spec.login) {
  await page.goto(spec.login.url, { waitUntil: "networkidle" });
  if (spec.login.kind === "django-admin") {
    await page.fill("input[name=username]", spec.login.user);
    await page.fill("input[name=password]", spec.login.pass);
    await Promise.all([page.waitForNavigation({ waitUntil: "networkidle" }), page.click("input[type=submit], button[type=submit]")]);
  } else {
    await page.fill("input[type=email], input[name=email]", spec.login.user);
    await page.fill("input[type=password]", spec.login.pass);
    await page.click("button[type=submit]");
    await page.waitForTimeout(1500);
  }
  report.push({ step: "login", url: page.url(), title: await page.title(), console: consoleMsgs, failed });
  consoleMsgs = []; failed = [];
}

for (const p of spec.pages) {
  apiLog.length = 0; await page.goto(p.url, { waitUntil: "networkidle" });
  if (p.waitFor) { try { await page.waitForSelector(p.waitFor, { timeout: 15000 }); } catch (e) { consoleMsgs.push(`[waitFor] ${p.waitFor} not found: ${e.message.split("\n")[0]}`); } }
  await page.waitForTimeout(p.settle ?? 800);
  await page.screenshot({ path: p.out, fullPage: true });
  const entry = { step: p.name, url: page.url(), title: await page.title(), console: consoleMsgs, failed, api: [...apiLog] };
  if (p.extract) { const fn = new Function("return (" + p.extract + ")")(); entry.extract = await page.evaluate(fn); }
  if (p.actions) { entry.actions = []; for (const a of p.actions) { apiLog.length = 0; try { if (a.click) await page.click(a.click); if (a.select) await page.selectOption(a.select.sel, a.select.value); if (a.fill) await page.fill(a.fill.sel, a.fill.value); await page.waitForTimeout(a.wait ?? 1200); if (a.out) await page.screenshot({ path: a.out, fullPage: true }); entry.actions.push({ name: a.name, api: [...apiLog], console: [...consoleMsgs], failed: [...failed], text: a.text ? await page.evaluate(new Function("return (" + a.text + ")")()) : undefined }); } catch (e) { entry.actions.push({ name: a.name, error: String(e).split("\n")[0] }); } consoleMsgs = []; failed = []; } }
  report.push(entry);
  consoleMsgs = []; failed = [];
}
writeFileSync(spec.reportOut, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
await browser.close();
