/**
 * Default per-kind inputs for <ResourceForm> (contract: string → Input,
 * text → Textarea, number/integer → Input[type=number], boolean → Switch,
 * date/datetime → native inputs, enum → Select, relation → ResourceSelect
 * (multiple for many), file → FileUpload, json → Textarea with validation).
 */
import * as React from "react";
import { Controller } from "react-hook-form";
import type { Control, FieldValues } from "react-hook-form";
import type { FieldDef } from "../../../schema/types";
import { FileUpload } from "../../file-upload/FileUpload";
import { Input } from "../../primitives/input";
import { Select } from "../../primitives/select";
import { Switch } from "../../primitives/switch";
import { Textarea } from "../../primitives/textarea";
import { ResourceSelect } from "../select/ResourceSelect";
import { humanizeValue } from "./prepare";

export interface DefaultFieldControlProps {
  field: FieldDef;
  control: Control<FieldValues>;
  inputId: string;
  describedBy?: string;
  invalid: boolean;
  disabled?: boolean;
  /** FieldOverride.props pass-through, spread onto the rendered input. */
  inputProps?: Record<string, unknown>;
}

function stringInputType(field: FieldDef): string {
  switch (field.format) {
    case "email":
      return "email";
    case "uri":
    case "url":
      return "url";
    case "password":
      return "password";
    default:
      return "text";
  }
}

export function DefaultFieldControl({
  field,
  control,
  inputId,
  describedBy,
  invalid,
  disabled,
  inputProps,
}: DefaultFieldControlProps): React.ReactElement {
  const aria = {
    "aria-invalid": invalid || undefined,
    "aria-describedby": describedBy,
  } as const;

  return (
    <Controller
      control={control}
      name={field.name}
      render={({ field: rhf }) => {
        switch (field.kind) {
          case "text":
            return (
              <Textarea
                id={inputId}
                rows={4}
                maxLength={field.maxLength}
                disabled={disabled}
                value={rhf.value == null ? "" : String(rhf.value)}
                onChange={(event) => rhf.onChange(event.target.value)}
                onBlur={rhf.onBlur}
                {...aria}
                {...inputProps}
              />
            );
          case "number":
          case "integer":
            return (
              <Input
                id={inputId}
                type="number"
                inputMode={field.kind === "integer" ? "numeric" : "decimal"}
                step={field.kind === "integer" ? 1 : "any"}
                min={field.min}
                max={field.max}
                disabled={disabled}
                value={rhf.value == null ? "" : (rhf.value as number | string)}
                onChange={(event) => rhf.onChange(event.target.value)}
                onBlur={rhf.onBlur}
                {...aria}
                {...inputProps}
              />
            );
          case "boolean":
            return (
              <Switch
                id={inputId}
                disabled={disabled}
                checked={Boolean(rhf.value)}
                onCheckedChange={(checked) => rhf.onChange(checked)}
                onBlur={rhf.onBlur}
                {...aria}
                {...inputProps}
              />
            );
          case "date":
            return (
              <Input
                id={inputId}
                type="date"
                disabled={disabled}
                value={rhf.value == null ? "" : String(rhf.value)}
                onChange={(event) => rhf.onChange(event.target.value)}
                onBlur={rhf.onBlur}
                {...aria}
                {...inputProps}
              />
            );
          case "datetime":
            return (
              <Input
                id={inputId}
                type="datetime-local"
                disabled={disabled}
                value={rhf.value == null ? "" : String(rhf.value)}
                onChange={(event) => rhf.onChange(event.target.value)}
                onBlur={rhf.onBlur}
                {...aria}
                {...inputProps}
              />
            );
          case "enum": {
            const members = field.enumValues ?? [];
            const options = members.map((member) => ({
              value: String(member),
              label: field.enumLabels?.[String(member)] ?? humanizeValue(String(member)),
            }));
            return (
              <Select
                id={inputId}
                disabled={disabled}
                value={rhf.value == null ? null : String(rhf.value)}
                options={options}
                clearable={field.nullable}
                placeholder="Select…"
                onValueChange={(next) => {
                  if (next === null) {
                    rhf.onChange(null);
                    return;
                  }
                  const member = members.find((candidate) => String(candidate) === next);
                  rhf.onChange(member ?? next);
                }}
                {...inputProps}
              />
            );
          }
          case "relation": {
            const relation = field.relation;
            if (relation === undefined) {
              // Degraded mode: no x-karni-relation extension, edit the raw pk.
              return (
                <Input
                  id={inputId}
                  type="text"
                  disabled={disabled}
                  value={rhf.value == null ? "" : String(rhf.value)}
                  onChange={(event) => rhf.onChange(event.target.value)}
                  onBlur={rhf.onBlur}
                  {...aria}
                  {...inputProps}
                />
              );
            }
            return (
              <ResourceSelect
                id={inputId}
                resource={relation.resource}
                multiple={relation.many}
                disabled={disabled}
                value={
                  (rhf.value ?? null) as string | number | ReadonlyArray<string | number> | null
                }
                onChange={(next) => rhf.onChange(next)}
                {...inputProps}
              />
            );
          }
          case "file":
            return (
              <FileUpload
                id={inputId}
                disabled={disabled}
                value={(rhf.value ?? null) as File | string | null}
                onChange={(next) => rhf.onChange(next)}
                {...inputProps}
              />
            );
          case "json":
            return (
              <Textarea
                id={inputId}
                rows={5}
                disabled={disabled}
                className="font-mono"
                value={
                  typeof rhf.value === "string"
                    ? rhf.value
                    : rhf.value == null
                      ? ""
                      : JSON.stringify(rhf.value, null, 2)
                }
                onChange={(event) => rhf.onChange(event.target.value)}
                onBlur={rhf.onBlur}
                {...aria}
                {...inputProps}
              />
            );
          default:
            return (
              <Input
                id={inputId}
                type={stringInputType(field)}
                maxLength={field.maxLength}
                disabled={disabled}
                value={rhf.value == null ? "" : String(rhf.value)}
                onChange={(event) => rhf.onChange(event.target.value)}
                onBlur={rhf.onBlur}
                {...aria}
                {...inputProps}
              />
            );
        }
      }}
    />
  );
}
