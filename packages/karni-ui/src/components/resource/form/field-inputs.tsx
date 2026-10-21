/**
 * Default per-kind inputs for <ResourceForm> (contract: string → Input,
 * text → Textarea, number/integer → Input[type=number], boolean → Switch,
 * date/datetime → native inputs, enum → Select, relation → ResourceSelect
 * (multiple for many), file → FileUpload, json → Textarea with validation).
 *
 * Every control receives react-hook-form's ref (so a failed submit can move
 * focus to it), `aria-invalid`, `aria-describedby` (help text and error) and,
 * where its role supports it, `aria-required`. A field that shows an error
 * re-validates on every change, so the error goes away as soon as the value
 * is fixed; a field without one validates when it loses focus.
 */
import * as React from "react";
import { Controller, useFormContext } from "react-hook-form";
import type { Control, ControllerRenderProps, FieldValues } from "react-hook-form";
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
  /** The label's id, for controls whose popup needs naming too (ResourceSelect's list). */
  labelId?: string;
  describedBy?: string;
  invalid: boolean;
  /** Sets `aria-required` on controls whose role supports it. */
  required?: boolean;
  disabled?: boolean;
  /** Re-validate on every change while the field shows an error. Default true. */
  revalidateWhileInvalid?: boolean;
  /** FieldOverride.props pass-through, spread onto the rendered input. */
  inputProps?: Record<string, unknown>;
}

/** Kinds whose control role cannot carry aria-required (their label says "required" instead). */
export const KINDS_WITHOUT_ARIA_REQUIRED: ReadonlySet<string> = new Set(["boolean", "file"]);

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

function textValue(value: unknown): string {
  return value == null ? "" : String(value);
}

export function DefaultFieldControl({
  field,
  control,
  inputId,
  labelId,
  describedBy,
  invalid,
  required = false,
  disabled,
  revalidateWhileInvalid = true,
  inputProps,
}: DefaultFieldControlProps): React.ReactElement {
  const { trigger } = useFormContext();
  const aria = {
    "aria-invalid": invalid || undefined,
    "aria-describedby": describedBy,
  } as const;
  const ariaRequired = required && !KINDS_WITHOUT_ARIA_REQUIRED.has(field.kind) ? true : undefined;

  return (
    <Controller
      control={control}
      name={field.name}
      render={({ field: rhf, fieldState }) => {
        const change = (next: unknown): void => {
          rhf.onChange(next);
          if (revalidateWhileInvalid && fieldState.invalid) void trigger(field.name);
        };
        return renderControl({
          field,
          rhf,
          change,
          inputId,
          labelId,
          aria,
          ariaRequired,
          disabled,
          inputProps,
        });
      }}
    />
  );
}

interface RenderControlInput {
  field: FieldDef;
  rhf: ControllerRenderProps<FieldValues, string>;
  change: (next: unknown) => void;
  inputId: string;
  labelId?: string;
  aria: { "aria-invalid": true | undefined; "aria-describedby": string | undefined };
  ariaRequired: true | undefined;
  disabled?: boolean;
  inputProps?: Record<string, unknown>;
}

function renderControl({
  field,
  rhf,
  change,
  inputId,
  labelId,
  aria,
  ariaRequired,
  disabled,
  inputProps,
}: RenderControlInput): React.ReactElement {
  switch (field.kind) {
    case "text":
      return (
        <Textarea
          ref={rhf.ref}
          id={inputId}
          name={rhf.name}
          rows={4}
          maxLength={field.maxLength}
          disabled={disabled}
          value={textValue(rhf.value)}
          onChange={(event) => change(event.target.value)}
          onBlur={rhf.onBlur}
          aria-required={ariaRequired}
          {...aria}
          {...inputProps}
        />
      );
    case "number":
    case "integer":
      return (
        <Input
          ref={rhf.ref}
          id={inputId}
          name={rhf.name}
          type="number"
          inputMode={field.kind === "integer" ? "numeric" : "decimal"}
          step={field.kind === "integer" ? 1 : "any"}
          min={field.min}
          max={field.max}
          disabled={disabled}
          value={rhf.value == null ? "" : (rhf.value as number | string)}
          onChange={(event) => change(event.target.value)}
          onBlur={rhf.onBlur}
          aria-required={ariaRequired}
          {...aria}
          {...inputProps}
        />
      );
    case "boolean":
      // A block of its own, so the switch sits under its label like every
      // other control (an inline switch ran into the label's text).
      return (
        <div>
          <Switch
            ref={rhf.ref}
            id={inputId}
            disabled={disabled}
            checked={Boolean(rhf.value)}
            onCheckedChange={(checked) => change(checked)}
            onBlur={rhf.onBlur}
            {...aria}
            {...inputProps}
          />
        </div>
      );
    case "date":
    case "datetime":
      return (
        <Input
          ref={rhf.ref}
          id={inputId}
          name={rhf.name}
          type={field.kind === "date" ? "date" : "datetime-local"}
          disabled={disabled}
          value={textValue(rhf.value)}
          onChange={(event) => change(event.target.value)}
          onBlur={rhf.onBlur}
          aria-required={ariaRequired}
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
          ref={rhf.ref}
          id={inputId}
          disabled={disabled}
          value={rhf.value == null ? null : String(rhf.value)}
          options={options}
          clearable={field.nullable}
          placeholder="Select…"
          onValueChange={(next) => {
            if (next === null) {
              change(null);
              return;
            }
            const member = members.find((candidate) => String(candidate) === next);
            change(member ?? next);
          }}
          onBlur={rhf.onBlur}
          aria-required={ariaRequired}
          {...aria}
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
            ref={rhf.ref}
            id={inputId}
            name={rhf.name}
            type="text"
            disabled={disabled}
            value={textValue(rhf.value)}
            onChange={(event) => change(event.target.value)}
            onBlur={rhf.onBlur}
            aria-required={ariaRequired}
            {...aria}
            {...inputProps}
          />
        );
      }
      return (
        <ResourceSelect
          ref={rhf.ref}
          id={inputId}
          resource={relation.resource}
          multiple={relation.many}
          disabled={disabled}
          value={(rhf.value ?? null) as string | number | ReadonlyArray<string | number> | null}
          onChange={(next) => change(next)}
          onBlur={rhf.onBlur}
          aria-labelledby={labelId}
          aria-required={ariaRequired}
          {...aria}
          {...inputProps}
        />
      );
    }
    case "file":
      return (
        <FileUpload
          ref={rhf.ref}
          id={inputId}
          name={rhf.name}
          disabled={disabled}
          value={(rhf.value ?? null) as File | string | null}
          onChange={(next) => change(next)}
          onBlur={rhf.onBlur}
          {...aria}
          {...inputProps}
        />
      );
    case "json":
      return (
        <Textarea
          ref={rhf.ref}
          id={inputId}
          name={rhf.name}
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
          onChange={(event) => change(event.target.value)}
          onBlur={rhf.onBlur}
          aria-required={ariaRequired}
          {...aria}
          {...inputProps}
        />
      );
    default:
      return (
        <Input
          ref={rhf.ref}
          id={inputId}
          name={rhf.name}
          type={stringInputType(field)}
          maxLength={field.maxLength}
          disabled={disabled}
          value={textValue(rhf.value)}
          onChange={(event) => change(event.target.value)}
          onBlur={rhf.onBlur}
          aria-required={ariaRequired}
          {...aria}
          {...inputProps}
        />
      );
  }
}
