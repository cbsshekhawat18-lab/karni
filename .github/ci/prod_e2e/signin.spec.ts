import { expect, test } from "playwright/test";

// The one browser test of the production-stack job (and of the same run by hand):
// the built staff app signs in and shows a ResourceTable page with rows.
//
//   E2E_BASE_URL   where the staff app is, with its path: https://localhost/app/
//                  in CI (Caddy), http://127.0.0.1:4173/ for a local `vite preview`.
//   E2E_USER, E2E_PASSWORD   an account that may read E2E_PAGE (the seed's demo login).
//   E2E_PAGE       the page with the ResourceTable, relative to the base: products
//   E2E_HEADING    that page's title: Products
//   E2E_CA         CI only: Caddy's local root certificate (the browser trusts it
//                  through ignoreHTTPSErrors, set in playwright.config.ts).
const user = process.env.E2E_USER ?? "demo@example.com";
const password = process.env.E2E_PASSWORD ?? "karni-password";
const page = (process.env.E2E_PAGE ?? "products").replace(/^\/+/, "");
const heading = process.env.E2E_HEADING ?? "Products";

test("sign in, then a ResourceTable page lists rows", async ({ page: browser }) => {
    // A failing API call is the usual reason this stalls: print it.
    browser.on("response", (response) => {
        if (response.status() >= 400 && response.url().includes("/api/")) {
            void response
                .text()
                .then((body) => console.log(`API ${response.status()} ${response.url()} ${body}`));
        }
    });

    await browser.goto(page);
    // Signed out, the page shows the sign-in form in place.
    await browser.getByLabel("Email").fill(user);
    await browser.getByLabel("Password").fill(password);
    await browser.getByRole("button", { name: "Sign in" }).click();

    await expect(browser.getByRole("heading", { name: heading })).toBeVisible();
    // ResourceTable renders an ARIA grid named after the resource.
    const table = browser.getByRole("grid", { name: heading });
    await expect(table).toBeVisible();
    // The header row plus at least one seeded row.
    await expect(table.getByRole("gridcell").first()).toBeVisible();
    expect(await table.getByRole("row").count()).toBeGreaterThan(1);
});
