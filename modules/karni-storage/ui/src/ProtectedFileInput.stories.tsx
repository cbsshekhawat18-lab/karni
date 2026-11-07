import { KarniProvider, ResourceForm, createKarniClient } from "@karni/ui";
import type { Meta, StoryObj } from "@storybook/react";
import { ProtectedFileInput } from "./ProtectedFileInput";
import type { BucketTransport } from "./transport";

/**
 * Stories run against a stubbed KarniClient (the client's injectable
 * `fetch`) and a fake bucket that reports progress over two seconds, so no
 * backend and no bucket are needed.
 */
function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const schema = {
  openapi: "3.0.3",
  info: { title: "Products", version: "1" },
  paths: {
    "/api/products/": {
      get: {
        operationId: "products_list",
        "x-karni-resource": "products",
        responses: { "200": { description: "" } },
      },
      post: {
        operationId: "products_create",
        requestBody: {
          content: {
            "multipart/form-data": { schema: { $ref: "#/components/schemas/ProductRequest" } },
          },
        },
        responses: { "201": { description: "" } },
      },
    },
  },
  components: {
    schemas: {
      ProductRequest: {
        type: "object",
        required: ["name"],
        properties: {
          name: { type: "string", maxLength: 100 },
          manual: { type: "string", format: "binary", nullable: true },
        },
      },
    },
  },
};

const client = createKarniClient({
  baseUrl: "/api",
  fetch: async (input) => {
    const url = String(input instanceof Request ? input.url : input);
    if (url.endsWith("/schema/")) return json(schema);
    if (url.endsWith("/upload/")) {
      return json({
        method: "put",
        url: "https://bucket.example.test/key",
        headers: { "Content-Type": "application/pdf" },
        token: "t",
        max_size: 10485760,
        content_types: ["application/pdf"],
      });
    }
    if (url.endsWith("/confirm/")) {
      return json({ token: "c", name: "guide.pdf", size: 1, content_type: "application/pdf" });
    }
    return json({ id: "p1", name: "Lamp", manual: null }, 201);
  },
});

const slowBucket: BucketTransport = (request) =>
  new Promise((resolve) => {
    let loaded = 0;
    const timer = window.setInterval(() => {
      loaded += 10;
      request.onProgress(loaded, 100);
      if (loaded >= 100) {
        window.clearInterval(timer);
        resolve();
      }
    }, 200);
  });

const meta = {
  title: "Storage/ProtectedFileInput",
  component: ResourceForm,
  tags: ["autodocs"],
  args: {
    resource: "products",
    fields: {
      manual: {
        component: ProtectedFileInput,
        props: { resource: "products", accept: "application/pdf", transport: slowBucket },
      },
    },
  },
  decorators: [
    (Story) => (
      <KarniProvider client={client}>
        <Story />
      </KarniProvider>
    ),
  ],
} satisfies Meta<typeof ResourceForm>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Pick a PDF: it goes to the (fake) bucket with progress, then the form saves its token. */
export const DirectUpload: Story = {};
