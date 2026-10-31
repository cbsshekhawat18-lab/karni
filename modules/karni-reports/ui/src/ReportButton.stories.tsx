import { KarniProvider, createKarniClient } from "@karni/ui";
import type { Meta, StoryObj } from "@storybook/react";
import { ReportButton } from "./ReportButton";

/**
 * Stories run against a stubbed KarniClient (the client's injectable `fetch`),
 * so no backend is needed. `save` is injected so the canvas never downloads.
 */
function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function state(status: string): Record<string, unknown> {
  return {
    id: "r1",
    report: "product-sheet",
    object_id: "7",
    status,
    url: status === "ready" ? "/api/reports/product-sheet/7/download/" : null,
    size: status === "ready" ? 2048 : 0,
    data_version: "abc",
    error: status === "failed" ? "REPORT007: the report could not be rendered." : "",
    requested_at: null,
    rendered_at: null,
    created_at: null,
  };
}

function client(final: "ready" | "failed" | "rendering") {
  let checks = 0;
  return createKarniClient({
    baseUrl: "/api",
    fetch: async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === "POST") return jsonResponse(state("pending"), 202);
      if (url.endsWith("/status/")) {
        checks += 1;
        return jsonResponse(state(checks < 2 ? "rendering" : final));
      }
      return new Response("%PDF-1.4 story", {
        headers: { "content-type": "application/pdf" },
      });
    },
  });
}

const meta = {
  title: "Reports/ReportButton",
  component: ReportButton,
  tags: ["autodocs"],
  args: {
    report: "product-sheet",
    objectId: 7,
    pollInterval: 600,
    save: (_blob: Blob, filename: string) => {
      window.alert(`Would save ${filename}`);
    },
  },
  decorators: [
    (Story) => (
      <KarniProvider client={client("ready")}>
        <Story />
      </KarniProvider>
    ),
  ],
} satisfies Meta<typeof ReportButton>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Playground: Story = {};

export const Outline: Story = {
  args: { variant: "outline", labels: { idle: "Product sheet (PDF)" } },
};

export const StillRendering: Story = {
  decorators: [
    (Story) => (
      <KarniProvider client={client("rendering")}>
        <Story />
      </KarniProvider>
    ),
  ],
};

export const Failed: Story = {
  decorators: [
    (Story) => (
      <KarniProvider client={client("failed")}>
        <Story />
      </KarniProvider>
    ),
  ],
};
