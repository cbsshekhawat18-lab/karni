import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { extractFixture, jobFixture, state } from "../tests/msw/server";
import { renderWithKarni } from "../tests/test-utils";
import { ExtractButton } from "./ExtractButton";

async function openAndExtract(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await user.click(screen.getByRole("button", { name: "Extract with AI" }));
  await user.type(screen.getByLabelText("Text to read"), "Name: Garden hose");
  await user.click(screen.getByRole("button", { name: "Extract" }));
}

describe("ExtractButton", () => {
  it("reads a text into the preview: rows, problems, counts, nothing saved", async () => {
    const user = userEvent.setup();
    const onExtracted = vi.fn();
    renderWithKarni(
      <ExtractButton resource="products" resourceLabel="products" onExtracted={onExtracted} />,
    );
    await openAndExtract(user);

    const dialog = await screen.findByRole("dialog", { name: "Extract products" });
    expect(await within(dialog).findByText(/Nothing is saved yet/)).toBeInTheDocument();
    const rows = within(dialog).getByRole("table", { name: "Proposed rows" });
    expect(within(rows).getByText("Garden hose")).toBeInTheDocument();
    expect(within(rows).getByText("outdoor, water")).toBeInTheDocument();
    const problems = within(dialog).getByRole("table", { name: "Problems" });
    expect(within(problems).getByText("'abc' is not in the expected form.")).toBeInTheDocument();
    expect(within(problems).getByText("Reading")).toBeInTheDocument();
    expect(within(problems).getByText("Preview")).toBeInTheDocument();
    expect(within(dialog).getByTestId("import-stats")).toHaveTextContent("Created1");
    expect(state.bodies).toEqual([{ resource: "products", text: "Name: Garden hose" }]);
    expect(onExtracted).toHaveBeenCalledTimes(1);
    expect(state.commits).toBe(0);
  });

  it("commits through the import's confirmation, then reports the rows saved", async () => {
    const user = userEvent.setup();
    const onDone = vi.fn();
    renderWithKarni(<ExtractButton resource="products" resourceLabel="products" onDone={onDone} />);
    await openAndExtract(user);

    await user.click(await screen.findByRole("button", { name: "Commit" }));
    const confirm = await screen.findByRole("dialog", { name: "Commit this import?" });
    expect(state.commits).toBe(0);
    await user.click(within(confirm).getByRole("button", { name: "Commit import" }));

    await waitFor(() => expect(state.commits).toBe(1));
    await waitFor(() =>
      expect(onDone).toHaveBeenCalledWith(expect.objectContaining({ status: "done" })),
    );
    expect(await screen.findByText("Saved to products: 1 row.")).toBeInTheDocument();
    expect(onDone.mock.calls[0]?.[0].id).toBe(jobFixture.id);
  });

  it("shows a refusal in the backend's words and keeps the form", async () => {
    state.answer = { code: "AI013", detail: "You have used 1000 of your 1000 tokens this month." };
    state.status = 429;
    const user = userEvent.setup();
    renderWithKarni(<ExtractButton resource="products" />);
    await openAndExtract(user);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Your monthly budget is spent");
    expect(alert).toHaveTextContent("You have used 1000 of your 1000 tokens this month.");
    expect(screen.getByLabelText("Text to read")).toHaveValue("Name: Garden hose");
  });

  it("offers only the sources it is given, and posts a URL", async () => {
    const user = userEvent.setup();
    renderWithKarni(
      <ExtractButton resource="products" sources={["url"]}>
        Read a page
      </ExtractButton>,
    );
    await user.click(screen.getByRole("button", { name: "Read a page" }));
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    expect(screen.getByText(/from a web page\./)).toBeInTheDocument();
    await user.type(screen.getByLabelText("Address of the page"), "https://shop.example.com/");
    await user.click(screen.getByRole("button", { name: "Extract" }));
    await screen.findByText(/Nothing is saved yet/);
    expect(state.bodies).toEqual([{ resource: "products", url: "https://shop.example.com/" }]);
  });

  it("uploads a PDF from its tab", async () => {
    const user = userEvent.setup();
    renderWithKarni(<ExtractButton resource="products" />);
    await user.click(screen.getByRole("button", { name: "Extract with AI" }));
    await user.click(screen.getByRole("tab", { name: "PDF" }));
    expect(screen.getByRole("button", { name: "Extract" })).toBeDisabled();
    const file = new File(["%PDF-1.4"], "list.pdf", { type: "application/pdf" });
    await user.upload(screen.getByLabelText("PDF file"), file);
    await user.click(screen.getByRole("button", { name: "Extract" }));
    await screen.findByText(/Nothing is saved yet/);
    expect(String(state.bodies[0]?.["multipart"])).toContain("Content-Type: application/pdf");
  });

  it("starts over from the preview", async () => {
    const user = userEvent.setup();
    renderWithKarni(<ExtractButton resource="products" />);
    await openAndExtract(user);
    await user.click(await screen.findByRole("button", { name: "Read another source" }));
    expect(screen.getByLabelText("Text to read")).toBeInTheDocument();
  });

  it("shows the progress of a preview running in Celery, then its counts", async () => {
    const running = { ...jobFixture, status: "previewing" as const, result: null, rows_done: 0 };
    state.answer = { ...extractFixture, status: "previewing", result: null, job: running };
    state.running = { job: running, times: 1 };
    const user = userEvent.setup();
    renderWithKarni(<ExtractButton resource="products" />);
    await openAndExtract(user);
    expect(await screen.findByRole("progressbar")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Commit" })).toBeDisabled();
    await waitFor(() => expect(screen.getByRole("button", { name: "Commit" })).toBeEnabled(), {
      timeout: 4000,
    });
    expect(screen.getByTestId("import-stats")).toHaveTextContent("Created1");
  });

  it("marks the trigger with its component role and passes Button props through", () => {
    renderWithKarni(<ExtractButton resource="products" variant="outline" disabled />);
    const trigger = screen.getByRole("button", { name: "Extract with AI" });
    expect(trigger).toHaveAttribute("data-karni-role", "extract-button");
    expect(trigger).toBeDisabled();
  });
});
