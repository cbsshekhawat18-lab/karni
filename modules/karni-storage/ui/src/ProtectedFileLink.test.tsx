import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { API_BASE, fakeApi, renderWithKarni } from "../tests/test-utils";
import { ProtectedFileLink, ProtectedImage } from "./ProtectedFileLink";

const PATH = `${API_BASE}/products/7/files/manual/`;
const LINK = {
  url: "https://bucket.example.test/guide.pdf?X-Amz-Signature=s",
  expires_in: 300,
  name: "guide.pdf",
};

describe("ProtectedFileLink", () => {
  it("asks for a signed link on click and opens it", async () => {
    const user = userEvent.setup();
    const api = fakeApi((call) => (call.url.startsWith(PATH) ? { body: LINK } : undefined));
    const open = vi.fn();
    renderWithKarni(
      <ProtectedFileLink href={PATH} open={open}>
        Manual
      </ProtectedFileLink>,
      api,
    );
    const link = screen.getByRole("link", { name: "Manual" });
    expect(link).toHaveAttribute("href", PATH);
    expect(api.calls).toEqual([]); // nothing fetched before the click
    await user.click(link);
    await waitFor(() => expect(open).toHaveBeenCalledWith(LINK.url));
    expect(api.calls[0]?.accept).toBe("application/json");
  });

  it("asks the client's own origin when the API gave an absolute URL on another host", async () => {
    const user = userEvent.setup();
    // What Django saw behind a dev proxy: its own host, not the page's.
    const api = fakeApi((call) =>
      call.url.startsWith(PATH) ? { body: LINK } : { status: 599, body: {} },
    );
    const open = vi.fn();
    renderWithKarni(
      <ProtectedFileLink href="http://127.0.0.1:8790/api/products/7/files/manual/" open={open}>
        Manual
      </ProtectedFileLink>,
      api,
    );
    await user.click(screen.getByRole("link", { name: "Manual" }));
    await waitFor(() => expect(open).toHaveBeenCalledWith(LINK.url));
    expect(api.calls[0]?.url).toBe(PATH);
  });

  it("asks for an attachment when download is set", async () => {
    const user = userEvent.setup();
    const api = fakeApi(() => ({ body: LINK }));
    const open = vi.fn();
    renderWithKarni(<ProtectedFileLink href={PATH} download open={open} />, api);
    await user.click(screen.getByRole("link", { name: "manual" }));
    await waitFor(() => expect(open).toHaveBeenCalled());
    expect(api.calls[0]?.url).toBe(`${PATH}?download=1`);
  });

  it("says so when the file cannot be opened", async () => {
    const user = userEvent.setup();
    const api = fakeApi(() => ({
      status: 404,
      body: { detail: "No Product matches the given query." },
    }));
    renderWithKarni(<ProtectedFileLink href={PATH}>Manual</ProtectedFileLink>, api);
    await user.click(screen.getByRole("link", { name: "Manual" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No Product matches");
  });

  it("renders nothing for an empty field", () => {
    const api = fakeApi(() => undefined);
    const { container } = renderWithKarni(<ProtectedFileLink href={null} />, api);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("ProtectedImage", () => {
  it("shows a thumbnail through its signed link", async () => {
    const thumb = {
      url: "https://bucket.example.test/t.webp?sig",
      expires_in: 300,
      name: "t.webp",
    };
    const api = fakeApi((call) => (call.url.includes("size=small") ? { body: thumb } : undefined));
    renderWithKarni(
      <ProtectedImage
        src={`${API_BASE}/products/7/files/photo/`}
        size="small"
        alt="Lamp"
        fallback="…"
      />,
      api,
    );
    expect(screen.getByText("…")).toBeInTheDocument();
    const image = await screen.findByRole("img", { name: "Lamp" });
    expect(image).toHaveAttribute("src", thumb.url);
  });
});
