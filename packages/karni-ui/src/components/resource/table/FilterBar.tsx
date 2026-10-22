/**
 * ResourceTable's search box + declared-params-derived filter bar (D5).
 *
 * The parent decides WHICH fields filter (enum/boolean/relation fields ∩ the
 * list operation's declared query params, cap 4, `filters` prop overrides);
 * this component only renders the controls:
 * - enum   → clearable <Select> ("All" clears),
 * - boolean → clearable Yes/No <Select>,
 * - relation → <ResourceSelect> (multiple for many-relations).
 *
 * Internal to @karni/ui — the public surface is ResourceTable's props.
 */
import * as React from "react";
import type { FilterValue } from "../../../hooks/types";
import type { FieldDef } from "../../../schema/types";
import { cn } from "../../../lib/cn";
import { Input } from "../../primitives/input";
import { Select } from "../../primitives/select";
import { ResourceSelect } from "../ResourceSelect";
import { enumLabel } from "./table-utils";

export interface FilterBarProps {
  /** Whether the list operation declares a `search` query param. */
  searchEnabled: boolean;
  searchValue: string;
  onSearchChange: (value: string) => void;
  searchPlaceholder?: string;
  /** Already-derived filter fields, in render order. */
  filterFields: readonly FieldDef[];
  values: Readonly<Record<string, FilterValue>>;
  onFilterChange: (field: FieldDef, value: FilterValue) => void;
  className?: string;
}

function toSelectValue(value: FilterValue): string | null {
  if (value === null || value === undefined || typeof value === "object") return null;
  return String(value);
}

function toRelationValue(
  value: FilterValue,
): string | number | ReadonlyArray<string | number> | null {
  if (value === null || value === undefined || typeof value === "boolean") return null;
  if (Array.isArray(value)) {
    return value.filter(
      (item): item is string | number => typeof item === "string" || typeof item === "number",
    );
  }
  return value as string | number;
}

function EnumFilter({
  field,
  value,
  onFilterChange,
}: {
  field: FieldDef;
  value: FilterValue;
  onFilterChange: FilterBarProps["onFilterChange"];
}): React.ReactElement {
  const options = (field.enumValues ?? []).map((member) => ({
    value: String(member),
    label: enumLabel(member, field.enumLabels),
  }));
  return (
    <Select
      aria-label={field.label}
      className="h-9 w-auto min-w-36"
      value={toSelectValue(value)}
      options={options}
      placeholder={field.label}
      clearable
      clearLabel={`${field.label}: All`}
      onValueChange={(next) => {
        if (next === null) {
          onFilterChange(field, null);
          return;
        }
        // Preserve the member's original type (numeric enums stay numbers).
        const member = (field.enumValues ?? []).find((candidate) => String(candidate) === next);
        onFilterChange(field, member ?? next);
      }}
    />
  );
}

function BooleanFilter({
  field,
  value,
  onFilterChange,
}: {
  field: FieldDef;
  value: FilterValue;
  onFilterChange: FilterBarProps["onFilterChange"];
}): React.ReactElement {
  return (
    <Select
      aria-label={field.label}
      className="h-9 w-auto min-w-36"
      value={typeof value === "boolean" ? String(value) : null}
      options={[
        { value: "true", label: "Yes" },
        { value: "false", label: "No" },
      ]}
      placeholder={field.label}
      clearable
      clearLabel={`${field.label}: All`}
      onValueChange={(next) => onFilterChange(field, next === null ? null : next === "true")}
    />
  );
}

/** Search box + up to four filter controls in one wrapping row. */
export function FilterBar(props: FilterBarProps): React.ReactElement {
  const {
    searchEnabled,
    searchValue,
    onSearchChange,
    searchPlaceholder = "Search…",
    filterFields,
    values,
    onFilterChange,
    className,
  } = props;

  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      {searchEnabled && (
        <Input
          type="search"
          aria-label="Search"
          placeholder={searchPlaceholder}
          value={searchValue}
          onChange={(event) => onSearchChange(event.target.value)}
          className="h-9 w-full max-w-80"
        />
      )}
      {filterFields.map((field) => {
        const value = values[field.name];
        if (field.kind === "enum") {
          return (
            <EnumFilter
              key={field.name}
              field={field}
              value={value}
              onFilterChange={onFilterChange}
            />
          );
        }
        if (field.kind === "boolean") {
          return (
            <BooleanFilter
              key={field.name}
              field={field}
              value={value}
              onFilterChange={onFilterChange}
            />
          );
        }
        if (field.kind === "relation" && field.relation !== undefined) {
          return (
            <div key={field.name} className="min-w-36">
              <ResourceSelect
                resource={field.relation.resource}
                multiple={field.relation.many}
                value={toRelationValue(value)}
                placeholder={field.label}
                // A placeholder is not a label: it disappears once a value is chosen.
                aria-label={field.label}
                onChange={(next) => onFilterChange(field, next)}
              />
            </div>
          );
        }
        return null;
      })}
    </div>
  );
}
