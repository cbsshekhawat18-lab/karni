/** The board's column order: the state machine's flow, closed states last, declared order breaks ties. */
import { describe, expect, it } from "vitest";
import { stageField } from "./board-fixtures";
import { boardColumns, flowOrder } from "./board-model";

describe("flowOrder", () => {
  it("follows the flow from the initial state, whatever order the choices are declared in", () => {
    const order = flowOrder(
      ["delivered", "cancelled", "shipped", "pending", "paid"],
      {
        pending: ["paid", "cancelled"],
        paid: ["shipped"],
        shipped: ["delivered"],
        delivered: [],
        cancelled: [],
      },
      ["pending"],
    );
    expect(order).toEqual(["pending", "paid", "shipped", "cancelled", "delivered"]);
  });

  it("puts a state as far along as its longest way in, and breaks a tie by the declared order", () => {
    const transitions = {
      lead: ["qualified", "lost"],
      qualified: ["won", "lost"],
      won: [],
      lost: [],
    };
    expect(flowOrder(["won", "lost", "qualified", "lead"], transitions, ["lead"])).toEqual([
      "lead",
      "qualified",
      "won",
      "lost",
    ]);
    expect(flowOrder(["lost", "won", "qualified", "lead"], transitions, ["lead"])).toEqual([
      "lead",
      "qualified",
      "lost",
      "won",
    ]);
  });

  it("ignores a way back, and starts where nothing leads in when no initial state is declared", () => {
    const order = flowOrder(
      ["closed", "open", "review", "draft"],
      { draft: ["open"], open: ["review", "closed"], review: ["open", "closed"], closed: ["open"] },
      undefined,
    );
    expect(order).toEqual(["draft", "open", "review", "closed"]);
  });

  it("puts states the flow never reaches after the reached ones, closed states still last", () => {
    const order = flowOrder(
      ["archived", "orphan", "done", "todo"],
      { todo: ["done"], done: [], orphan: ["archived"], archived: [] },
      ["todo"],
    );
    expect(order).toEqual(["todo", "orphan", "done", "archived"]);
  });
});

describe("boardColumns", () => {
  it("orders the columns by the flow, and keeps the declared order without transitions", () => {
    const outOfOrder = { ...stageField, enumValues: ["won", "lost", "qualified", "lead"] };
    expect(boardColumns(outOfOrder).map((column) => column.value)).toEqual([
      "lead",
      "qualified",
      "won",
      "lost",
    ]);
    const plain = { ...outOfOrder, transitions: undefined };
    expect(boardColumns(plain).map((column) => column.value)).toEqual([
      "won",
      "lost",
      "qualified",
      "lead",
    ]);
  });
});
