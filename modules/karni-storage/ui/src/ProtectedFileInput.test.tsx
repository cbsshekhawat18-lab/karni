import { ResourceForm } from "@karni/ui";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import {
  API_BASE,
  CONFIRM_ANSWER,
  POST_ANSWER,
  PRODUCTS_SCHEMA,
  fakeApi,
  readText,
  recordingTransport,
  renderWithKarni,
} from "../tests/test-utils";
import type { Route } from "../tests/test-utils";
import { ProtectedFileInput } from "./ProtectedFileInput";
import { UPLOAD_REFERENCE_TYPE } from "./types";

function route(upload: unknown): Route {
  return (call) => {
    if (call.url.endsWith("/api/schema/")) return { body: PRODUCTS_SCHEMA };
    if (call.url.endsWith("/products/files/manual/upload/")) return { body: upload };
    if (call.url.endsWith("/products/files/manual/confirm/")) return { body: CONFIRM_ANSWER };
    if (call.url === `${API_BASE}/products/` && call.method === "POST") {
      return { status: 201, body: { id: "p1", name: "Lamp", manual: null } };
    }
    return undefined;
  };
}

function renderForm(upload: unknown) {
  const api = fakeApi(route(upload));
  const bucket = recordingTransport();
  renderWithKarni(
    <ResourceForm
      resource="products"
      fields={{
        manual: {
          component: ProtectedFileInput,
          props: { resource: "products", transport: bucket.transport },
        },
      }}
    />,
    api,
  );
  return { api, bucket };
}

describe("ProtectedFileInput in ResourceForm", () => {
  it("uploads the picked file to the bucket and saves the row with the confirmed token", async () => {
    const user = userEvent.setup();
    const { api, bucket } = renderForm(POST_ANSWER);
    await user.type(await screen.findByLabelText(/name/i), "Lamp");
    const input = document.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();
    const file = new File(["%PDF-1."], "guide.pdf", { type: "application/pdf" });
    await user.upload(input as HTMLInputElement, file);
    await waitFor(() => expect(api.calls.some((c) => c.url.endsWith("/confirm/"))).toBe(true));
    expect(bucket.requests).toHaveLength(1);
    expect(screen.getByText("guide.pdf")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /create|save/i }));
    await waitFor(() =>
      expect(api.calls.some((c) => c.method === "POST" && c.url === `${API_BASE}/products/`)).toBe(
        true,
      ),
    );
    const created = api.calls.find((c) => c.method === "POST" && c.url === `${API_BASE}/products/`);
    const form = created?.body as FormData;
    expect(form).toBeInstanceOf(FormData);
    expect(form.get("name")).toBe("Lamp");
    const sent = form.get("manual") as File;
    expect(sent.type).toBe(UPLOAD_REFERENCE_TYPE);
    expect(await readText(sent)).toBe("confirmed-token");
  });

  it("sends the file itself with the row on local storage", async () => {
    const user = userEvent.setup();
    const { api, bucket } = renderForm({ method: "api", max_size: 1048576, content_types: [] });
    await user.type(await screen.findByLabelText(/name/i), "Lamp");
    const input = document.querySelector<HTMLInputElement>('input[type="file"]');
    const file = new File(["%PDF-1."], "guide.pdf", { type: "application/pdf" });
    await user.upload(input as HTMLInputElement, file);
    await waitFor(() => expect(screen.getByText("guide.pdf")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /create|save/i }));
    await waitFor(() =>
      expect(api.calls.some((c) => c.method === "POST" && c.url === `${API_BASE}/products/`)).toBe(
        true,
      ),
    );
    const created = api.calls.find((c) => c.method === "POST" && c.url === `${API_BASE}/products/`);
    const sent = (created?.body as FormData).get("manual") as File;
    expect(sent.type).toBe("application/pdf");
    expect(bucket.requests).toEqual([]);
  });

  it("shows the server's refusal and keeps the form's value", async () => {
    const user = userEvent.setup();
    const api = fakeApi((call) => {
      if (call.url.endsWith("/api/schema/")) return { body: PRODUCTS_SCHEMA };
      if (call.url.endsWith("/upload/")) {
        return {
          status: 400,
          body: ["STORE011: The file is 5242880 bytes. manual takes at most 1048576."],
        };
      }
      return undefined;
    });
    renderWithKarni(
      <ResourceForm
        resource="products"
        fields={{ manual: { component: ProtectedFileInput, props: { resource: "products" } } }}
      />,
      api,
    );
    await screen.findByLabelText(/name/i);
    const input = document.querySelector<HTMLInputElement>('input[type="file"]');
    await user.upload(
      input as HTMLInputElement,
      new File(["x"], "big.pdf", { type: "application/pdf" }),
    );
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("big.pdf")).not.toBeInTheDocument();
  });
});
