/**
 * <ResourceBoard> over an in-memory deals API: columns in the flow's order,
 * totals, legal moves by menu, keyboard and drag, rollback on a refusal, the
 * declared row action path, and the unhappy states.
 */
import { QueryClient } from "@tanstack/react-query";
import { fireEvent, render as renderUi, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { axeViolations } from "../../../tests/axe";
import { server } from "../../../tests/msw/server";
import { AuthContext, type AuthContextValue } from "../../auth/provider";
import type { KarniUser } from "../../auth/types";
import { createKarniClient } from "../../schema/client";
import { KarniProvider } from "../../schema/provider";
import type { ResourceSchema } from "../../schema/types";
import { useSchema, type UseSchemaResult } from "../../schema/useSchema";
import { dealsSchema, deals, stageField, type DealRow } from "./board-fixtures";
import { ResourceBoard, type ResourceBoardProps } from "./ResourceBoard";

vi.mock("../../schema/useSchema", () => ({ useSchema: vi.fn() }));
const mockUseSchema = useSchema as unknown as Mock<(resource: string) => UseSchemaResult>;

const USER: KarniUser = { id: 1, email: "ada@example.com", roles: ["sales"] };
const auth: AuthContextValue = {
  user: USER,
  roles: USER.roles,
  status: "authenticated",
  login: () => Promise.resolve({ ok: true, user: USER }),
  logout: () => Promise.resolve(),
  refresh: () => Promise.resolve(),
  adoptTokens: () => Promise.resolve(),
};

let rows: DealRow[] = [];
const patches: unknown[] = [];

function useSchemaOf(schema: ResourceSchema): void {
  mockUseSchema.mockReturnValue({ data: schema, isLoading: false, error: undefined });
}

function serve(): void {
  server.use(
    http.get("*/api/deals/", ({ request }) => {
      const url = new URL(request.url);
      const stage = url.searchParams.get("stage");
      const size = Number(url.searchParams.get("page_size") ?? "50");
      const found = rows.filter((row) => stage === null || row.stage === stage);
      return HttpResponse.json({
        count: found.length,
        next: null,
        previous: null,
        results: found.slice(0, size),
      });
    }),
    http.patch("*/api/deals/:id/", async ({ request, params }) => {
      const body = (await request.json()) as Partial<DealRow>;
      patches.push(body);
      const row = rows.find((candidate) => String(candidate.id) === params["id"]);
      if (row === undefined) return HttpResponse.json({}, { status: 404 });
      Object.assign(row, body);
      return HttpResponse.json(row);
    }),
  );
}

function render(props: Partial<ResourceBoardProps<DealRow>> = {}) {
  const client = createKarniClient({ baseUrl: "http://karni.test/api" });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return renderUi(
    <KarniProvider client={client} queryClient={queryClient}>
      <AuthContext.Provider value={auth}>
        <ResourceBoard<DealRow>
          resource="deals"
          field="stage"
          totalField="value"
          renderCard={(deal) => <p>{deal.title}</p>}
          {...props}
        />
      </AuthContext.Provider>
    </KarniProvider>,
  );
}

async function column(name: string): Promise<HTMLElement> {
  return screen.findByRole("region", { name });
}

beforeEach(() => {
  rows = deals();
  patches.length = 0;
  useSchemaOf(dealsSchema());
  serve();
});

describe("ResourceBoard", () => {
  it("makes a column per choice in order, with the count and the sum of each", async () => {
    render();
    const lead = await column("Lead");
    await within(lead).findByText("Roof repair");
    expect(within(lead).getByText("2")).toBeInTheDocument();
    expect(within(lead).getByText(/\$2,000\.50/)).toBeInTheDocument();
    const names = screen.getAllByRole("region").map((node) => node.getAttribute("aria-label"));
    expect(names).toEqual(["Lead", "Qualified", "Won", "Lost"]);
    const won = await column("Won");
    expect(await within(won).findByText("Kitchen")).toBeInTheDocument();
    expect(within(won).getByText(/\$5,000\.00/)).toBeInTheDocument();
    const lost = await column("Lost");
    expect(await within(lost).findByText("Nothing here")).toBeInTheDocument();
  });

  it("orders the columns by the state machine's flow, not by how the choices are declared", async () => {
    const field = { ...stageField, enumValues: ["won", "lost", "qualified", "lead"] };
    const fields = dealsSchema().fields.map((each) => (each.name === "stage" ? field : each));
    useSchemaOf(dealsSchema({ fields }));
    render();
    await column("Lead");
    expect(screen.getAllByRole("region").map((node) => node.getAttribute("aria-label"))).toEqual([
      "Lead",
      "Qualified",
      "Won",
      "Lost",
    ]);
  });

  it("shows only the columns asked for, in that order", async () => {
    render({ columns: ["won", "lead"] });
    await column("Won");
    expect(screen.getAllByRole("region").map((node) => node.getAttribute("aria-label"))).toEqual([
      "Won",
      "Lead",
    ]);
  });

  it("offers only the legal targets in a card's menu, and none from a terminal state", async () => {
    render();
    const menu = await screen.findByLabelText("Move Roof repair to");
    const options = within(menu)
      .getAllByRole("option")
      .map((option) => option.textContent);
    expect(options).toEqual(["Move to…", "Qualified", "Lost"]);
    await screen.findByText("Kitchen");
    expect(screen.queryByLabelText("Move Kitchen to")).toBeNull();
  });

  it("moves a card by its menu: PATCHes the state and the card lands in the new column", async () => {
    const user = userEvent.setup();
    render();
    const menu = await screen.findByLabelText("Move Roof repair to");
    await user.selectOptions(menu, "Qualified");
    await waitFor(() => expect(patches).toEqual([{ stage: "qualified" }]));
    const qualified = await column("Qualified");
    await waitFor(() => expect(within(qualified).getByText("Roof repair")).toBeInTheDocument());
    const lead = await column("Lead");
    await waitFor(() => expect(within(lead).queryByText("Roof repair")).toBeNull());
    expect(await screen.findByText("Moved Roof repair to Qualified.")).toBeInTheDocument();
  });

  it("moves at once, and puts the card back with the server's sentence when it refuses", async () => {
    const user = userEvent.setup();
    server.use(
      http.patch("*/api/deals/:id/", async () => {
        await new Promise((resolve) => setTimeout(resolve, 50));
        return HttpResponse.json(
          {
            stage: [
              "E980: Deal 1: stage cannot go from 'lead' to 'qualified'. See https://x.test/e",
            ],
          },
          { status: 400 },
        );
      }),
    );
    render();
    const menu = await screen.findByLabelText("Move Roof repair to");
    await user.selectOptions(menu, "Qualified");
    const qualified = await column("Qualified");
    expect(within(qualified).getByText("Roof repair")).toBeInTheDocument();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't move Roof repair to Qualified");
    expect(alert).toHaveTextContent("Deal 1: stage cannot go from 'lead' to 'qualified'.");
    expect(alert).not.toHaveTextContent("E980");
    const lead = await column("Lead");
    await waitFor(() => expect(within(lead).getByText("Roof repair")).toBeInTheDocument());
    expect(within(qualified).queryByText("Roof repair")).toBeNull();
  });

  it("moves a card with the keyboard: Shift and the arrows, focus stays on the card", async () => {
    const user = userEvent.setup();
    render();
    const card = await screen.findByRole("article", { name: "Roof repair" });
    card.focus();
    await user.keyboard("{Shift>}{ArrowRight}{/Shift}");
    await waitFor(() => expect(patches).toEqual([{ stage: "qualified" }]));
    await waitFor(() => expect(screen.getByRole("article", { name: "Roof repair" })).toHaveFocus());
    const qualified = await column("Qualified");
    expect(within(qualified).getByRole("article", { name: "Roof repair" })).toBeInTheDocument();
  });

  it("moves focus between cards with the arrows, and opens one with Enter", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render({ onOpen });
    const first = await screen.findByRole("article", { name: "Roof repair" });
    first.focus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("article", { name: "Office fit-out" })).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("article", { name: "Garden" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ id: 3 }));
  });

  it("moves a card by a drag to a legal column, and refuses a drop on an illegal one", async () => {
    render();
    const card = await screen.findByRole("article", { name: "Roof repair" });
    const store: Record<string, string> = {};
    const dataTransfer = {
      setData: (type: string, value: string) => {
        store[type] = value;
      },
      getData: (type: string) => store[type] ?? "",
      effectAllowed: "",
      dropEffect: "",
    };
    fireEvent.dragStart(card, { dataTransfer });
    const won = await column("Won");
    expect(won).toHaveAttribute("data-drop", "refused");
    fireEvent.dragOver(won, { dataTransfer });
    fireEvent.drop(won, { dataTransfer });
    expect(patches).toEqual([]);
    fireEvent.dragEnd(card, { dataTransfer });

    fireEvent.dragStart(card, { dataTransfer });
    const qualified = await column("Qualified");
    expect(qualified).toHaveAttribute("data-drop", "allowed");
    fireEvent.dragOver(qualified, { dataTransfer });
    fireEvent.drop(qualified, { dataTransfer });
    await waitFor(() => expect(patches).toEqual([{ stage: "qualified" }]));
  });

  it("uses the declared row action when one makes the move, and a read-only field needs one", async () => {
    const user = userEvent.setup();
    const posted: string[] = [];
    server.use(
      http.post("*/api/deals/:id/qualify/", ({ params }) => {
        posted.push(String(params["id"]));
        const row = rows.find((candidate) => String(candidate.id) === params["id"]);
        if (row !== undefined) row.stage = "qualified";
        return HttpResponse.json(row);
      }),
    );
    useSchemaOf(
      dealsSchema({
        fields: dealsSchema().fields.map((field) =>
          field.name === "stage" ? { ...stageField, readOnly: true } : field,
        ),
        rowActions: {
          qualify: { from: ["lead"], to: "qualified", field: "stage", by: null, requires: [] },
        },
      }),
    );
    render();
    const menu = await screen.findByLabelText("Move Roof repair to");
    expect(
      within(menu)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Move to…", "Qualified"]);
    await user.selectOptions(menu, "Qualified");
    await waitFor(() => expect(posted).toEqual(["1"]));
    expect(patches).toEqual([]);
    const qualified = await column("Qualified");
    await waitFor(() => expect(within(qualified).getByText("Roof repair")).toBeInTheDocument());
  });

  it("offers no move to a role the action's rule refuses, and honours canMove", async () => {
    useSchemaOf(
      dealsSchema({
        rowActions: {
          qualify: {
            from: ["lead"],
            to: "qualified",
            field: "stage",
            by: { role: ["manager"] },
            requires: [],
          },
        },
      }),
    );
    render({ canMove: (_row, _from, to) => to !== "lost" });
    await screen.findByText("Roof repair");
    expect(screen.queryByLabelText("Move Roof repair to")).toBeNull();
  });

  it("offers no move when the update rule refuses the role", async () => {
    const schema = dealsSchema();
    useSchemaOf({
      ...schema,
      operations: {
        ...schema.operations,
        update: {
          ...(schema.operations.update as NonNullable<typeof schema.operations.update>),
          access: { role: ["manager"] },
        },
      },
    });
    render();
    await screen.findByText("Roof repair");
    expect(screen.queryByLabelText(/^Move /)).toBeNull();
  });

  it("loads more cards on request, and says the sum covers the loaded ones", async () => {
    const user = userEvent.setup();
    render({ pageSize: 1 });
    const lead = await column("Lead");
    await within(lead).findByText("Roof repair");
    expect(within(lead).queryByText("Office fit-out")).toBeNull();
    expect(within(lead).getByText(/\$1,200\.00\+/)).toBeInTheDocument();
    await user.click(within(lead).getByRole("button", { name: "Show more Lead" }));
    expect(await within(lead).findByText("Office fit-out")).toBeInTheDocument();
  });

  it("explains a failed column and retries it", async () => {
    server.use(http.get("*/api/deals/", () => HttpResponse.json({}, { status: 500 })));
    render({ columns: ["lead"] });
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("shows a loading state while the schema loads, and the Error slot when it fails", () => {
    mockUseSchema.mockReturnValue({ data: undefined, isLoading: true, error: undefined });
    const { container, unmount } = render();
    expect(container.querySelector('[aria-hidden="true"]')).not.toBeNull();
    unmount();
    mockUseSchema.mockReturnValue({ data: undefined, isLoading: false, error: new Error("boom") });
    render({ slots: { Error: () => <p>custom failure</p> } });
    expect(screen.getByText("custom failure")).toBeInTheDocument();
  });

  it("says plainly when the resource has no state field", () => {
    useSchemaOf(dealsSchema({ fields: dealsSchema().fields.filter((f) => f.name !== "stage") }));
    render({ field: undefined });
    expect(screen.getByRole("alert")).toHaveTextContent("no state field");
  });

  it("lets a slot replace the column header and the empty column", async () => {
    render({
      slots: {
        ColumnHeader: ({ column, count }) => <h3>{`${column.label}: ${count}`}</h3>,
        Empty: () => <p>No deals here</p>,
      },
    });
    expect(await screen.findByRole("heading", { name: "Lead: 2" })).toBeInTheDocument();
    expect(await screen.findByText("No deals here")).toBeInTheDocument();
  });

  it("has no axe violations", async () => {
    const { container } = render({ onOpen: () => undefined });
    await screen.findByRole("article", { name: "Roof repair" });
    expect(await axeViolations(container)).toEqual([]);
  });
});
