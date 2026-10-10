import { createHash } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";

// Runs against the seeded database (`karni seed --reset --seed 42`): the
// logins and the "Open Source Summit" numbers below come from events/seeds.py.
const API = process.env.E2E_API_URL ?? "http://127.0.0.1:8000";
const PASSWORD = "karni-password";
const TEST_PROVIDER_SECRET = "karni-test-secret";

// A failing API call is the usual reason a journey stalls: print its body.
test.beforeEach(({ page }) => {
    page.on("response", (response) => {
        if (response.status() >= 400 && response.url().includes("/api/")) {
            void response
                .text()
                .then((body) => console.log(`API ${response.status()} ${response.url()} ${body}`));
        }
    });
});

async function login(page: Page, email: string) {
    await page.goto("/login");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/events$/);
}

test("anonymous visitors browse and search published events", async ({ page }) => {
    await page.goto("/events");
    await expect(page.getByRole("heading", { name: "Events" })).toBeVisible();
    await expect(page.getByText("Open Source Summit")).toBeVisible();
    await expect(page.getByText("Winter Film Night")).toHaveCount(0); // a draft
    await expect(page.getByRole("button", { name: "New event" })).toHaveCount(0);

    await page.getByPlaceholder(/search/i).fill("Jazz");
    await expect(page.getByText("Jazz by the River")).toBeVisible();
    await expect(page.getByText("Open Source Summit")).toHaveCount(0);
});

test("an attendee books, pays, and is confirmed by the provider webhook", async ({ page }) => {
    await login(page, "attendee@example.com");
    await page.getByText("Open Source Summit").click();
    await expect(page.getByRole("heading", { name: "Tickets" })).toBeVisible();
    await page.getByRole("button", { name: "Book" }).first().click();
    await expect(page).toHaveURL(/\/bookings\/new\?event=/);
    await page.getByLabel("Quantity").fill("2");
    await page.getByRole("button", { name: /save|create/i }).click();
    await expect(page).toHaveURL(/\/bookings\/[0-9a-f-]{36}$/);
    const bookingId = page.url().split("/").pop() as string;

    // The hosted checkout is the test provider's imaginary page.
    await page.route("https://checkout.test/**", (route) =>
        route.fulfill({ contentType: "text/html", body: "<h1>Test checkout</h1>" }),
    );
    await page.getByRole("button", { name: "Pay now" }).click();
    await expect(page.getByText("Test checkout")).toBeVisible();
    const sessionId = new URL(page.url()).pathname.split("/").pop() as string;

    // The provider calls back: a signed webhook, processed by the Celery worker.
    const body = JSON.stringify({
        id: `evt_${sessionId}_${Date.now()}`, // ids are replay-protected per provider
        type: "payment.succeeded",
        status: "succeeded",
        checkout_session_id: sessionId,
    });
    const signature = createHash("sha256")
        .update(body + TEST_PROVIDER_SECRET)
        .digest("hex");
    const hook = await page.request.post(`${API}/payments/webhook/test/`, {
        data: body,
        headers: { "Content-Type": "application/json", "X-Test-Signature": signature },
    });
    expect(hook.ok()).toBeTruthy();

    await expect
        .poll(
            async () => {
                const response = await page.request.get(`/api/bookings/${bookingId}/`);
                return ((await response.json()) as { status: string }).status;
            },
            { timeout: 30_000 },
        )
        .toBe("confirmed");
    await page.goto(`/bookings/${bookingId}?paid=1`);
    await expect(page.getByText("Payment received")).toBeVisible();
    await expect(page.getByText("Confirmed", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Pay now" })).toHaveCount(0);
});

test("an organizer creates an event and reads the dashboard", async ({ page }) => {
    await login(page, "organizer@example.com");

    await page.getByRole("button", { name: "New event" }).click();
    await page.getByLabel("Title").fill("Playwright Launch Party");
    await page.getByLabel("Description").fill("Created by the end-to-end suite.");
    await page.getByLabel(/starts/i).fill("2027-03-01T18:00");
    await page.getByLabel(/ends/i).fill("2027-03-01T21:00");
    await page.getByLabel("Venue").click();
    await page.getByRole("option").first().click();
    await page.getByRole("button", { name: /save|create/i }).click();
    await expect(page).toHaveURL(/\/events\/[0-9a-f-]{36}$/);
    await expect(page.getByText("Playwright Launch Party")).toBeVisible();

    // A seeded event no other journey touches (events/seeds.py, second event):
    // General is pending (not counted), 1 x VIP (90.00) is confirmed.
    await page.goto("/events");
    await page.getByText("Jazz by the River").click();
    await page.getByRole("button", { name: "Dashboard" }).click();
    await expect(page.getByText("Confirmed bookings", { exact: true })).toBeVisible();
    await expect(page.getByText("90.00")).toBeVisible();
    await expect(page.getByText("1 / 120")).toBeVisible();

    const download = page.waitForEvent("download");
    await page.getByRole("link", { name: /export attendees/i }).click();
    const csv = await (await download).createReadStream();
    const text = await new Promise<string>((resolve) => {
        let data = "";
        csv.on("data", (chunk: Buffer) => (data += chunk.toString()));
        csv.on("end", () => resolve(data));
    });
    expect(text).toContain("email,tier,quantity,booked_at");
    expect(text).toContain("attendee@example.com");
});
