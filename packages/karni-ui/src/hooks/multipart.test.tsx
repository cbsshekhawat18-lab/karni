/**
 * D2 multipart encoding tests: FormData dispatch, array/json/null rules, and
 * the PATCH omission of unchanged file URLs — unit-level plus end-to-end
 * through the real client against msw.
 */
import { QueryClient } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { parseMultipartEntries, type MultipartEntry } from "../../tests/msw/handlers";
import { server } from "../../tests/msw/server";
import { createKarniClient } from "../schema/client";
import { KarniProvider } from "../schema/provider";
import { karniKeys } from "./keys";
import {
  containsFile,
  encodeBody,
  fileFieldNames,
  omitUnchangedFileUrls,
  toFormData,
} from "./multipart";
import { useResourceMutations } from "./useResourceMutations";

const BASE = "http://karni.test/api";

function makeFile(name = "photo.png"): File {
  return new File(["binary-bytes"], name, { type: "image/png" });
}

describe("containsFile / encodeBody (D2 dispatch)", () => {
  it("detects a top-level File and an array containing one", () => {
    expect(containsFile({ photo: makeFile() })).toBe(true);
    expect(containsFile({ attachments: ["kept.png", makeFile()] })).toBe(true);
    expect(containsFile({ title: "x", count: 1, meta: { nested: makeFile() } })).toBe(false);
  });

  it("returns the payload untouched (JSON path) when no File is present", () => {
    const values = { title: "x", tags: [1, 2] };
    expect(encodeBody(values)).toBe(values);
  });

  it("returns FormData when a File is present", () => {
    expect(encodeBody({ photo: makeFile() })).toBeInstanceOf(FormData);
  });
});

describe("toFormData (D2 encoding rules)", () => {
  it("appends arrays as repeated keys, json as strings, scalars stringified, null omitted", () => {
    const file = makeFile();
    const form = toFormData({
      photo: file,
      title: "Launch",
      capacity: 10,
      is_public: true,
      tags: [1, 2],
      metadata: { a: 1 },
      cleared: null,
      skipped: undefined,
    });
    expect(form.get("photo")).toBe(file);
    expect(form.get("title")).toBe("Launch");
    expect(form.get("capacity")).toBe("10");
    expect(form.get("is_public")).toBe("true");
    expect(form.getAll("tags")).toEqual(["1", "2"]);
    expect(form.get("metadata")).toBe(JSON.stringify({ a: 1 }));
    expect(form.has("cleared")).toBe(false);
    expect(form.has("skipped")).toBe(false);
  });

  it("encodes array members by the same rules (files kept, nulls dropped)", () => {
    const file = makeFile("b.png");
    const form = toFormData({ attachments: [file, null, { k: 1 }] });
    const entries = form.getAll("attachments");
    expect(entries).toHaveLength(2);
    expect(entries[0]).toBe(file);
    expect(entries[1]).toBe(JSON.stringify({ k: 1 }));
  });
});

describe("fileFieldNames (guarded schema-cache read)", () => {
  const parsed = {
    resources: {
      events: {
        resource: "events",
        operations: {},
        fields: [
          { name: "title", kind: "string" },
          { name: "photo", kind: "file" },
          { name: "gallery", kind: "file" },
        ],
      },
    },
  };

  it("extracts file-kind field names for the resource", () => {
    expect([...fileFieldNames(parsed, "events")].sort()).toEqual(["gallery", "photo"]);
  });

  it("never throws on unexpected shapes", () => {
    for (const garbage of [undefined, null, 42, "x", {}, { resources: 1 }, { resources: {} }]) {
      expect([...fileFieldNames(garbage, "events")]).toEqual([]);
    }
  });
});

describe("omitUnchangedFileUrls (D2 PATCH rule)", () => {
  const fileFields = new Set(["photo"]);

  it("drops string URLs (and all-string arrays) on file fields, keeps Files", () => {
    const file = makeFile();
    expect(omitUnchangedFileUrls({ title: "x", photo: "https://cdn/x.png" }, fileFields)).toEqual({
      title: "x",
    });
    expect(omitUnchangedFileUrls({ photo: ["https://cdn/a.png"] }, fileFields)).toEqual({});
    expect(omitUnchangedFileUrls({ photo: file }, fileFields)).toEqual({ photo: file });
    expect(omitUnchangedFileUrls({ photo: null }, fileFields)).toEqual({ photo: null });
  });

  it("leaves string values on non-file fields alone", () => {
    expect(omitUnchangedFileUrls({ title: "kept" }, fileFields)).toEqual({ title: "kept" });
  });
});

// end-to-end through the client + msw

function setup() {
  const client = createKarniClient({ baseUrl: BASE });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <KarniProvider client={client} queryClient={queryClient}>
      {children}
    </KarniProvider>
  );
  return { queryClient, wrapper };
}

/** Groups parsed multipart parts by field name (repeated keys → arrays). */
function partsByName(entries: readonly MultipartEntry[], name: string): MultipartEntry[] {
  return entries.filter((entry) => entry.name === name);
}

describe("mutations with files (D2 end-to-end)", () => {
  it("creates with multipart FormData and no manual Content-Type", async () => {
    const { wrapper } = setup();
    let contentType: string | null = null;
    let entries: MultipartEntry[] = [];
    server.use(
      http.post(`${BASE}/events/`, async ({ request }) => {
        contentType = request.headers.get("content-type");
        // Not request.formData(): undici cannot decode file parts under jsdom
        // (it hangs) — see parseMultipartEntries in tests/msw/handlers.ts.
        entries = parseMultipartEntries(await request.text(), contentType ?? "");
        return HttpResponse.json({ id: 1 }, { status: 201 });
      }),
    );

    const { result } = renderHook(() => useResourceMutations("events"), { wrapper });
    await act(async () => {
      await result.current.create.mutateAsync({
        title: "Launch",
        photo: makeFile(),
        tags: [1, 2],
      });
    });

    // The runtime set the boundary itself — multipart, not JSON.
    expect(contentType).toMatch(/^multipart\/form-data; boundary=/);
    expect(partsByName(entries, "title").map((entry) => entry.value)).toEqual(["Launch"]);
    expect(partsByName(entries, "tags").map((entry) => entry.value)).toEqual(["1", "2"]);
    const uploaded = partsByName(entries, "photo");
    expect(uploaded).toHaveLength(1);
    expect(uploaded[0]?.filename).toBe("photo.png"); // a real file part, not a string
    expect(uploaded[0]?.value).toBe("binary-bytes");
  });

  it("PATCHes multipart too, omitting unchanged file URLs via the cached schema", async () => {
    const { queryClient, wrapper } = setup();
    queryClient.setQueryData(karniKeys.schema(), {
      resources: {
        events: {
          resource: "events",
          operations: {},
          fields: [
            { name: "title", kind: "string" },
            { name: "photo", kind: "file" },
            { name: "banner", kind: "file" },
          ],
        },
      },
    });
    let entries: MultipartEntry[] = [];
    server.use(
      http.patch(`${BASE}/events/5/`, async ({ request }) => {
        entries = parseMultipartEntries(
          await request.text(),
          request.headers.get("content-type") ?? "",
        );
        return HttpResponse.json({ id: 5 });
      }),
    );

    const { result } = renderHook(() => useResourceMutations("events"), { wrapper });
    await act(async () => {
      await result.current.update.mutateAsync({
        id: 5,
        values: {
          title: "New",
          banner: makeFile("banner.png"), // changed → uploaded
          photo: "https://cdn.example.com/old.png", // unchanged URL → omitted
        },
      });
    });

    expect(partsByName(entries, "title").map((entry) => entry.value)).toEqual(["New"]);
    const banner = partsByName(entries, "banner");
    expect(banner).toHaveLength(1);
    expect(banner[0]?.filename).toBe("banner.png"); // a real file part
    expect(partsByName(entries, "photo")).toHaveLength(0);
  });

  it("omits unchanged file URLs from JSON PATCHes as well", async () => {
    const { queryClient, wrapper } = setup();
    queryClient.setQueryData(karniKeys.schema(), {
      resources: {
        events: {
          resource: "events",
          operations: {},
          fields: [{ name: "photo", kind: "file" }],
        },
      },
    });
    const patched: unknown[] = [];
    server.use(
      http.patch(`${BASE}/events/5/`, async ({ request }) => {
        patched.push(await request.json());
        return HttpResponse.json({ id: 5 });
      }),
    );

    const { result } = renderHook(() => useResourceMutations("events"), { wrapper });
    await act(async () => {
      await result.current.update.mutateAsync({
        id: 5,
        values: { title: "New", photo: "https://cdn.example.com/old.png" },
      });
    });
    expect(patched).toEqual([{ title: "New" }]);
  });

  it("degrades gracefully without a cached schema (no omission)", async () => {
    const { wrapper } = setup();
    const patched: unknown[] = [];
    server.use(
      http.patch(`${BASE}/events/5/`, async ({ request }) => {
        patched.push(await request.json());
        return HttpResponse.json({ id: 5 });
      }),
    );

    const { result } = renderHook(() => useResourceMutations("events"), { wrapper });
    await act(async () => {
      await result.current.update.mutateAsync({
        id: 5,
        values: { photo: "https://cdn.example.com/old.png" },
      });
    });
    expect(patched).toEqual([{ photo: "https://cdn.example.com/old.png" }]);
  });
});
