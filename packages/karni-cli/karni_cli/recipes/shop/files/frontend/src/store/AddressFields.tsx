// An address, field by field. The country list comes from the API's schema (the Address
// entity's country field), so it follows karni.yaml.
import { Input, Label, Select, useSchema } from "@karni/ui";
import { useId } from "react";
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

const FIELDS: {
  key: keyof Address;
  label: string;
  required: boolean;
  auto: string;
}[] = [
  { key: "name", label: "Full name", required: true, auto: "name" },
  { key: "company", label: "Company", required: false, auto: "organization" },
  { key: "line1", label: "Address", required: true, auto: "address-line1" },
  {
    key: "line2",
    label: "Address, line 2",
    required: false,
    auto: "address-line2",
  },
  { key: "city", label: "City", required: true, auto: "address-level2" },
  {
    key: "region",
    label: "Region or state",
    required: false,
    auto: "address-level1",
  },
  { key: "postcode", label: "Postcode", required: true, auto: "postal-code" },
  { key: "phone", label: "Phone", required: false, auto: "tel" },
];

function useCountries(): { value: string; label: string }[] {
  const field = useSchema("addresses").data?.fields.find(
    (found) => found.name === "country",
  );
  return (field?.enumValues ?? []).map((value) => ({
    value: String(value),
    label: field?.enumLabels?.[String(value)] ?? String(value),
  }));
}

export function AddressFields({
  legend,
  value,
  onChange,
  errors,
  section,
}: {
  legend: string;
  value: Address;
  onChange: (next: Address) => void;
  errors?: Record<string, string>;
  section: string;
}) {
  const base = useId();
  const countries = useCountries();
  const field = (
    key: keyof Address,
    label: string,
    required: boolean,
    auto: string,
  ) => (
    <div key={key} className="flex flex-col gap-1">
      <Label htmlFor={`${base}-${key}`}>
        {label}
        {required ? null : (
          <span className="text-muted-foreground"> (optional)</span>
        )}
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
  );
  return (
    <fieldset className="grid gap-3 sm:grid-cols-2">
      <legend className="mb-2 text-lg font-semibold">{legend}</legend>
      {FIELDS.map((item) =>
        field(item.key, item.label, item.required, item.auto),
      )}
      <div className="flex flex-col gap-1">
        <Label id={`${base}-country`}>Country</Label>
        {countries.length > 0 ? (
          <Select
            aria-labelledby={`${base}-country`}
            value={value.country || null}
            options={countries}
            placeholder="Choose a country"
            onValueChange={(country) =>
              onChange({ ...value, country: country ?? "" })
            }
          />
        ) : (
          <Input
            aria-labelledby={`${base}-country`}
            maxLength={2}
            value={value.country}
            onChange={(event) =>
              onChange({ ...value, country: event.target.value.toUpperCase() })
            }
          />
        )}
        {errors?.country ? (
          <span className="text-sm text-destructive">{errors.country}</span>
        ) : null}
      </div>
    </fieldset>
  );
}
