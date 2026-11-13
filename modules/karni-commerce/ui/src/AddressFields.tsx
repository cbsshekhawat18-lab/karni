/** An address, field by field, with the browser's autofill names and the server's errors. */
import { Input, Label, Select } from "@karni/ui";
import { useId, useMemo } from "react";
import { countryOptions } from "./countries";
import type { Address } from "./types";

export const EMPTY_ADDRESS: Address = {
  name: "",
  company: "",
  line1: "",
  line2: "",
  city: "",
  region: "",
  postcode: "",
  country: "",
  phone: "",
};

const FIELDS: { key: keyof Address; label: string; required: boolean; auto: string }[] = [
  { key: "name", label: "Full name", required: true, auto: "name" },
  { key: "company", label: "Company", required: false, auto: "organization" },
  { key: "line1", label: "Address", required: true, auto: "address-line1" },
  { key: "line2", label: "Address, line 2", required: false, auto: "address-line2" },
  { key: "city", label: "City", required: true, auto: "address-level2" },
  { key: "region", label: "Region or state", required: false, auto: "address-level1" },
  { key: "postcode", label: "Postcode", required: true, auto: "postal-code" },
  { key: "phone", label: "Phone", required: false, auto: "tel" },
];

export interface AddressFieldsProps {
  legend: string;
  value: Address;
  onChange: (next: Address) => void;
  /** The server's message per field. */
  errors?: Record<string, string>;
  /** The autofill section: "billing" or "shipping". */
  section: string;
  /** The country choices (default: every country). */
  countries?: { value: string; label: string }[];
}

export function AddressFields({
  legend,
  value,
  onChange,
  errors,
  section,
  countries,
}: AddressFieldsProps) {
  const base = useId();
  const choices = useMemo(() => countries ?? countryOptions(), [countries]);
  return (
    <fieldset className="grid gap-3 sm:grid-cols-2">
      <legend className="mb-2 text-lg font-semibold">{legend}</legend>
      {FIELDS.map(({ key, label, required, auto }) => (
        <div key={key} className="flex flex-col gap-1">
          <Label htmlFor={`${base}-${key}`}>
            {label}
            {required ? null : <span className="text-muted-foreground"> (optional)</span>}
          </Label>
          <Input
            id={`${base}-${key}`}
            autoComplete={`${section} ${auto}`}
            required={required}
            aria-invalid={errors?.[key] ? true : undefined}
            aria-describedby={errors?.[key] ? `${base}-${key}-error` : undefined}
            value={value[key] ?? ""}
            onChange={(event) => onChange({ ...value, [key]: event.target.value })}
          />
          {errors?.[key] ? (
            <span id={`${base}-${key}-error`} className="text-sm text-destructive">
              {errors[key]}
            </span>
          ) : null}
        </div>
      ))}
      <div className="flex flex-col gap-1">
        <Label id={`${base}-country`}>Country</Label>
        <Select
          aria-labelledby={`${base}-country`}
          value={value.country || null}
          options={choices}
          placeholder="Choose a country"
          onValueChange={(country) => onChange({ ...value, country: country ?? "" })}
        />
        {errors?.country ? (
          <span className="text-sm text-destructive">{errors.country}</span>
        ) : null}
      </div>
    </fieldset>
  );
}
