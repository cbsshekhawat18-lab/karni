/**
 * ResourceDetail's related tabs (`related={["deals", "people"]}`): one tab per
 * reverse relation, each a ResourceTable of the related resource filtered to
 * this row.
 *
 * The backend publishes each model's reverse relations as `x-karni-related`
 * on its list operation: the related resource, the field that points here,
 * the list parameter that filters by it and the field whose value it takes.
 * So nothing is guessed here. A tab names a relation by its name (its related
 * name), by its resource, or as `resource.field` when two relations lead to
 * the same resource. A relation the user may not list is left out. Only the
 * open tab's table loads.
 *
 * Internal to @karni/ui. The public surface is ResourceDetail's `related`
 * prop and its `Related` slot.
 */
import * as React from "react";
import type { KarniQueryValue } from "../../../schema/client";
import type { RelatedDef, ResourceSchema } from "../../../schema/types";
import { useParsedSchema } from "../../../schema/useSchema";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../primitives/tabs";
import { ResourceTable, type ResourceTableProps } from "../ResourceTable";
import type { AccessIdentity } from "../table/access";
import { evaluateAccess } from "../table/access";

/** One related tab, as ResourceDetail's `related` takes it in place of a name. */
export interface ResourceDetailRelated {
  /** The relation: its name, its resource, or `resource.field`. */
  name: string;
  /** The tab's label (default: the relation's, "Deals"). */
  label?: string;
  /** More ResourceTable props for this tab (columns, onRowClick, pageSize, ...). */
  table?: Omit<ResourceTableProps, "resource" | "params">;
}

/** One tab, resolved against the schema. */
export interface ResourceDetailRelatedTab {
  /** What the page asked for. */
  name: string;
  label: string;
  /** The relation, or undefined when the schema has none of that name. */
  relation: RelatedDef | undefined;
  /** The list parameters that narrow the table to this row, or undefined when it cannot be. */
  params: Readonly<Record<string, KarniQueryValue>> | undefined;
  /** Why the tab has no table, in words, when it has none. */
  problem: string | undefined;
  table: Omit<ResourceTableProps, "resource" | "params"> | undefined;
}

/** What the `Related` slot receives: the tabs, resolved, and the row. */
export interface ResourceDetailRelatedProps {
  tabs: readonly ResourceDetailRelatedTab[];
  item: Record<string, unknown>;
  /** The resource in words, singular ("company"). */
  resourceLabel: string;
}

/** The relation `name` asks for: by name, by `resource.field`, or by resource when only one leads there. */
export function findRelation(related: readonly RelatedDef[], name: string): RelatedDef | undefined {
  const byName = related.find((relation) => relation.name === name);
  if (byName !== undefined) return byName;
  const byField = related.find((relation) => `${relation.resource}.${relation.field}` === name);
  if (byField !== undefined) return byField;
  const byResource = related.filter((relation) => relation.resource === name);
  return byResource.length === 1 ? byResource[0] : undefined;
}

function keyValue(
  item: Record<string, unknown>,
  key: string,
  id: string | number,
): KarniQueryValue {
  const value = item[key];
  if (typeof value === "string" || typeof value === "number") return value;
  if (value !== null && typeof value === "object") {
    const nested = (value as Record<string, unknown>)["id"];
    if (typeof nested === "string" || typeof nested === "number") return nested;
  }
  return id;
}

/** The tabs `requested` names, resolved against `schema` (exported for tests and the slot). */
export function resolveRelatedTabs(
  requested: ReadonlyArray<string | ResourceDetailRelated>,
  schema: ResourceSchema,
  resources: Readonly<Record<string, ResourceSchema>>,
  item: Record<string, unknown>,
  id: string | number,
  identity: AccessIdentity | null,
  resourceLabel: string,
): ResourceDetailRelatedTab[] {
  const related = schema.related ?? [];
  const tabs: ResourceDetailRelatedTab[] = [];
  for (const entry of requested) {
    const options: ResourceDetailRelated = typeof entry === "string" ? { name: entry } : entry;
    const relation = findRelation(related, options.name);
    if (relation === undefined) {
      const known = related.map((candidate) => candidate.name).join(", ") || "none";
      tabs.push({
        name: options.name,
        label: options.label ?? options.name,
        relation: undefined,
        params: undefined,
        problem:
          `${schema.resource} has no related rows named "${options.name}" (its relations: ${known}). ` +
          "Name a relation, its resource, or resource.field.",
        table: options.table,
      });
      continue;
    }
    const target = resources[relation.resource];
    // A list the user may not read: no tab (the server would refuse it anyway).
    if (evaluateAccess(target?.operations.list?.access, identity) === false) continue;
    tabs.push({
      name: options.name,
      label: options.label ?? relation.label,
      relation,
      params:
        relation.param === null
          ? undefined
          : { [relation.param]: keyValue(item, relation.key, id) },
      problem:
        relation.param === null
          ? `The ${relation.resource} list has no filter on ${relation.field}, so it cannot ` +
            `show only the rows of this ${resourceLabel}. Add ${relation.field} to its filters.`
          : undefined,
      table: options.table,
    });
  }
  return tabs;
}

/** Karni's related tabs: Radix tabs, one ResourceTable each (only the open one loads). */
export function DefaultRelated({ tabs }: ResourceDetailRelatedProps): React.ReactElement | null {
  const [active, setActive] = React.useState<string | undefined>(undefined);
  if (tabs.length === 0) return null;
  const value =
    active !== undefined && tabs.some((tab) => tab.name === active) ? active : tabs[0]?.name;
  return (
    <Tabs value={value} onValueChange={setActive}>
      <TabsList aria-label="Related records" className="max-w-full justify-start overflow-x-auto">
        {tabs.map((tab) => (
          <TabsTrigger key={tab.name} value={tab.name}>
            {tab.label}
          </TabsTrigger>
        ))}
      </TabsList>
      {tabs.map((tab) => (
        <TabsContent key={tab.name} value={tab.name}>
          {tab.relation !== undefined && tab.params !== undefined ? (
            <ResourceTable
              caption={tab.label}
              syncUrl={false}
              columns={[{ field: tab.relation.field, hidden: true }]}
              {...tab.table}
              resource={tab.relation.resource}
              params={tab.params}
            />
          ) : (
            <p
              role="note"
              className="rounded-md border border-border px-4 py-3 text-sm text-muted-foreground"
            >
              {tab.problem}
            </p>
          )}
        </TabsContent>
      ))}
    </Tabs>
  );
}

/**
 * Resolves the tabs against the whole schema (access to each related list
 * included) and renders the `Related` slot. Rendered by ResourceDetail only
 * when its `related` prop names a tab.
 */
export function RelatedTabs(props: {
  requested: ReadonlyArray<string | ResourceDetailRelated>;
  schema: ResourceSchema;
  item: Record<string, unknown>;
  id: string | number;
  identity: AccessIdentity | null;
  resourceLabel: string;
  Related: React.ComponentType<ResourceDetailRelatedProps>;
}): React.ReactElement | null {
  const { requested, schema, item, id, identity, resourceLabel, Related } = props;
  const parsed = useParsedSchema();
  const resources = parsed.data?.resources;
  const tabs = React.useMemo(
    () => resolveRelatedTabs(requested, schema, resources ?? {}, item, id, identity, resourceLabel),
    [requested, schema, resources, item, id, identity, resourceLabel],
  );
  if (tabs.length === 0) return null;
  return <Related tabs={tabs} item={item} resourceLabel={resourceLabel} />;
}
