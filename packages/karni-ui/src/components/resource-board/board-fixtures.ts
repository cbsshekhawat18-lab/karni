/** A deals schema and an in-memory API for the ResourceBoard tests and stories. */
import type { FieldDef, OperationDef, ResourceSchema } from "../../schema/types";

export type DealRow = Record<string, unknown> & {
  id: number;
  title: string;
  stage: string;
  value: string;
};

const base = { required: false, readOnly: false, writeOnly: false, nullable: false };

export const stageField: FieldDef = {
  ...base,
  name: "stage",
  label: "Stage",
  kind: "enum",
  order: 2,
  enumValues: ["lead", "qualified", "won", "lost"],
  enumLabels: { lead: "Lead", qualified: "Qualified", won: "Won", lost: "Lost" },
  transitions: { lead: ["qualified", "lost"], qualified: ["won", "lost"], won: [], lost: [] },
  initial: ["lead"],
};

export const valueField: FieldDef = {
  ...base,
  name: "value",
  label: "Value",
  kind: "string",
  order: 3,
  money: { currency: "USD" },
};

const op = (method: OperationDef["method"], access?: OperationDef["access"]): OperationDef => ({
  method,
  path: "/deals/",
  queryParams: ["stage", "page", "page_size"],
  ...(access !== undefined ? { access } : {}),
});

export function dealsSchema(overrides: Partial<ResourceSchema> = {}): ResourceSchema {
  return {
    resource: "deals",
    operations: { list: op("get"), update: op("patch") },
    fields: [
      { ...base, name: "id", label: "Id", kind: "integer", readOnly: true, order: 0 },
      { ...base, name: "title", label: "Title", kind: "string", order: 1 },
      stageField,
      valueField,
    ],
    ...overrides,
  };
}

export function deals(): DealRow[] {
  return [
    { id: 1, title: "Roof repair", stage: "lead", value: "1200.0000" },
    { id: 2, title: "Office fit-out", stage: "lead", value: "800.5000" },
    { id: 3, title: "Garden", stage: "qualified", value: "300.0000" },
    { id: 4, title: "Kitchen", stage: "won", value: "5000.0000" },
  ];
}
