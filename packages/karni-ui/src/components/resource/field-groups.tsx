/**
 * Field groups (experimental): the sections or tabs of ResourceForm and
 * ResourceDetail for a model with many fields.
 *
 * The backend publishes a model's `Karni.field_groups` as
 * `x-karni-field-groups` on its list operation: titled groups, in order, and
 * whether they show as sections or tabs. The fields a screen shows are split
 * into those groups, and the ones in no group form a last group, "Other". A
 * form shows each group as a `<fieldset>` with its legend, a detail page as a
 * `<section>` with a heading. As tabs, every panel stays mounted (a form keeps
 * its inputs registered) and only the open one shows. A form opens a field's
 * tab before it moves focus there.
 *
 * Internal to @karni/ui. The public surface is the `fieldGroups` and
 * `groupLayout` props of ResourceForm and ResourceDetail.
 */
import { HEADING_TAGS, type HeadingLevel } from "../../lib/heading";
import * as React from "react";
import { cn } from "../../lib/cn";
import type { FieldGroupDef, FieldGroupLayout, ResourceSchema } from "../../schema/types";
import { AlertIcon } from "../primitives/icons";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../primitives/tabs";

/** The title of the last group: the fields no declared group lists. */
export const REST_GROUP = "Other";

/** One group as a screen shows it: its fields, in order. */
export interface ShownGroup<F extends { name: string }> {
  /** Stable across renders (the tab's value). */
  key: string;
  label: string;
  fields: F[];
}

/**
 * The groups a screen uses: the `fieldGroups` prop (`false` for none), else
 * the schema's. `undefined` means no groups: the flat list.
 */
export function chosenGroups(
  prop: false | readonly FieldGroupDef[] | undefined,
  schema: ResourceSchema | undefined,
): readonly FieldGroupDef[] | undefined {
  if (prop === false) return undefined;
  const groups = prop ?? schema?.fieldGroups?.groups;
  return groups !== undefined && groups.length > 0 ? groups : undefined;
}

/** The layout a screen uses: the `groupLayout` prop, else the schema's, else sections. */
export function chosenLayout(
  prop: FieldGroupLayout | undefined,
  schema: ResourceSchema | undefined,
): FieldGroupLayout {
  return prop ?? schema?.fieldGroups?.layout ?? "sections";
}

/**
 * Splits `fields` into `groups` (their order, each group's fields in its own
 * order), then the rest in `fields` order. A group with none of `fields` is
 * left out. `null` without groups.
 */
export function groupFields<F extends { name: string }>(
  fields: readonly F[],
  groups: readonly FieldGroupDef[] | undefined,
): Array<ShownGroup<F>> | null {
  if (groups === undefined) return null;
  const byName = new Map(fields.map((field) => [field.name, field]));
  const placed = new Set<string>();
  const shown: Array<ShownGroup<F>> = [];
  groups.forEach((group, index) => {
    const members: F[] = [];
    for (const name of group.fields) {
      const field = byName.get(name);
      if (field === undefined || placed.has(name)) continue;
      placed.add(name);
      members.push(field);
    }
    if (members.length > 0)
      shown.push({ key: `group-${index}`, label: group.label, fields: members });
  });
  const rest = fields.filter((field) => !placed.has(field.name));
  if (rest.length > 0) shown.push({ key: "group-rest", label: REST_GROUP, fields: rest });
  return shown;
}

/** One panel of the layout: a group's title, what it shows, and how many of its fields fail. */
export interface GroupPanel {
  key: string;
  label: string;
  content: React.ReactNode;
  /** Fields with an error: a tab marks itself so a hidden problem is still seen. */
  problems?: number;
}

export interface GroupedFieldsProps {
  layout: FieldGroupLayout;
  panels: readonly GroupPanel[];
  /** `fieldset` (a form: each group a fieldset and its legend) or `section` (a detail page). */
  as: "fieldset" | "section";
  /** Names the tab list for assistive technology ("Event fields"). */
  label: string;
  /** The open tab (controlled), and its change. Uncontrolled without them. */
  active?: string;
  onActiveChange?: (key: string) => void;
  className?: string;
  /** The level of a group's heading on a detail page (`as="section"`). Default 3. */
  headingLevel?: HeadingLevel;
}

function PanelBody({
  panel,
  as,
  headingHidden,
  headingLevel,
}: {
  panel: GroupPanel;
  as: "fieldset" | "section";
  headingHidden: boolean;
  headingLevel: HeadingLevel;
}): React.ReactElement {
  const headingId = React.useId();
  const title = cn(
    "text-sm font-semibold tracking-tight text-foreground",
    headingHidden && "sr-only",
  );
  if (as === "fieldset") {
    return (
      <fieldset className="m-0 min-w-0 space-y-5 border-0 p-0" data-karni-group={panel.label}>
        <legend className={cn(title, !headingHidden && "mb-4")}>{panel.label}</legend>
        {panel.content}
      </fieldset>
    );
  }
  const Heading = HEADING_TAGS[headingLevel];
  return (
    <section aria-labelledby={headingId} data-karni-group={panel.label}>
      <Heading id={headingId} className={cn(title, !headingHidden && "mb-1")}>
        {panel.label}
      </Heading>
      {panel.content}
    </section>
  );
}

/** The groups as sections one after another, or as tabs. */
export function GroupedFields(props: GroupedFieldsProps): React.ReactElement | null {
  const { layout, panels, as, label, active, onActiveChange, className, headingLevel = 3 } = props;
  const [own, setOwn] = React.useState<string | undefined>(undefined);
  const first = panels[0];
  if (first === undefined) return null;
  if (layout === "sections") {
    return (
      <div className={cn(as === "fieldset" ? "space-y-8" : "space-y-6", className)}>
        {panels.map((panel) => (
          <PanelBody
            key={panel.key}
            panel={panel}
            as={as}
            headingHidden={false}
            headingLevel={headingLevel}
          />
        ))}
      </div>
    );
  }
  const wanted = active ?? own;
  const value = panels.some((panel) => panel.key === wanted) ? (wanted as string) : first.key;
  const change = (next: string): void => {
    if (active === undefined) setOwn(next);
    onActiveChange?.(next);
  };
  return (
    <Tabs value={value} onValueChange={change} className={className}>
      <TabsList aria-label={label} className="h-auto max-w-full flex-wrap justify-start">
        {panels.map((panel) => (
          <TabsTrigger key={panel.key} value={panel.key} className="gap-1.5">
            {panel.label}
            {panel.problems !== undefined && panel.problems > 0 ? (
              <>
                <AlertIcon aria-hidden="true" className="h-3.5 w-3.5 text-destructive" />
                <span className="sr-only">
                  {panel.problems === 1
                    ? " (1 field needs attention)"
                    : ` (${panel.problems} fields need attention)`}
                </span>
              </>
            ) : null}
          </TabsTrigger>
        ))}
      </TabsList>
      {panels.map((panel) => (
        // Mounted while closed (hidden): a form's inputs stay registered with their values.
        <TabsContent
          key={panel.key}
          value={panel.key}
          forceMount
          hidden={panel.key !== value}
          className="mt-4"
        >
          <PanelBody panel={panel} as={as} headingHidden headingLevel={headingLevel} />
        </TabsContent>
      ))}
    </Tabs>
  );
}
