// Records the README demo (docs/assets/karni-demo.gif): the quickstart's
// terminal output (replayed from terminal.html), then the running app: the
// welcome page, the admin's event list, sign-in and the React events table.
// Run by scripts/demo/record-demo.sh; see that file for setup.
const { chromium } = require(process.env.PW || "playwright");
const out = process.env.OUT;
const API = process.env.API_URL || "http://127.0.0.1:8000";
const APP = process.env.APP_URL || "http://localhost:5173";
(async () => {
  const browser = await chromium.launch();
  const size = { width: 1280, height: 800 };
  const context = await browser.newContext({
    viewport: size,
    recordVideo: { dir: out, size },
  });
  const page = await context.newPage();
  const pause = (ms) => page.waitForTimeout(ms);
  await page.goto(
    "file://" + require("node:path").join(__dirname, "terminal.html"),
  );
  await page.waitForFunction(() => window.done === true, null, {
    timeout: 60000,
  });
  await pause(1200);
  // the welcome page Django serves at /
  await page.goto(API + "/", { waitUntil: "networkidle" });
  await pause(2600);
  await page.mouse.move(640, 500);
  await page.mouse.wheel(0, 380);
  await pause(1600);
  // the admin: no admin.py was written
  await page.goto(API + "/admin/login/", { waitUntil: "networkidle" });
  await page.fill("input[name=username]", "demo@example.com");
  await page.fill("input[name=password]", "karni-password");
  await pause(500);
  await page.click("button[type=submit], input[type=submit]");
  await page.waitForLoadState("networkidle");
  await pause(1200);
  await page.goto(API + "/admin/events/event/", { waitUntil: "networkidle" });
  await pause(2600);
  // the React app on @karni/ui
  await page.goto(APP + "/login", { waitUntil: "networkidle" });
  await page.getByLabel(/email/i).fill("demo@example.com");
  await page.getByLabel(/password/i).fill("karni-password");
  await pause(500);
  await page.getByRole("button", { name: /sign in|log in/i }).click();
  await page.waitForURL(APP + "/", { timeout: 15000 });
  await pause(600);
  await page.getByRole("link", { name: "Events" }).click();
  await page.waitForLoadState("networkidle");
  await page.locator("tbody tr").first().waitFor();
  await pause(2800);
  await page.locator("tbody tr").first().click();
  await page.waitForLoadState("networkidle");
  await pause(2200);
  await context.close();
  await browser.close();
})();
