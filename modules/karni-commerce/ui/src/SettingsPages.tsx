/**
 * The staff's pages for what checkout charges: coupons, shipping
 * zones with their methods, and tax rates. Each is @karni/ui's ResourceTable
 * with New and Edit in a dialog (ResourceForm), so the roles' grants decide
 * who may see and change them, and a project's extra fields show up too.
 *
 * A coupon's limits are picked by name: items (any kind for sale, searched as
 * staff placing an order by hand search them) and the coupon keys selling apps
 * register (`registerCouponLimit`, the shop's categories).
 */
import {
  Button,
  Input,
  Label,
  Modal,
  Page,
  ResourceForm,
  ResourceTable,
  useKarniClient,
  useResourceItem,
  useResourceList,
  type ResourceColumn,
} from "@karni/ui";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useId, useState, type ReactNode } from "react";
import { couponLimits, type CouponLimit } from "./couponLimits";
import type { SellableItem } from "./types";

type Row = Record<string, unknown>;

interface Editing {
  id: string | null;
}

/** A named value a coupon keeps: `{key, name}`. */
export interface NamedKey {
  key: string;
  name: string;
}

function named(values: unknown): NamedKey[] {
  if (!Array.isArray(values)) return [];
  return values.map((value) =>
    value !== null && typeof value === "object"
      ? {
          key: String((value as Row)["key"] ?? ""),
          name: String((value as Row)["name"] ?? (value as Row)["key"] ?? ""),
        }
      : { key: String(value), name: String(value) },
  );
}

interface RecordsProps {
  resource: string;
  itemLabel: string;
  columns: ReadonlyArray<ResourceColumn>;
  /** Fixed list filters (a zone's methods: `{zone: id}`). */
  params?: Record<string, string>;
  /** Values a new row starts with, and fields the form hides. */
  defaults?: Record<string, unknown>;
  hidden?: readonly string[];
  /** More inputs below the generated ones, for the row being edited (or null for a new one). */
  extra?: (id: string | null) => ReactNode;
  /** Adds what `extra` holds to the values sent. */
  transform?: (values: Row) => Row;
  onRowClick?: (row: Row) => void;
}

/** A table of rows with New and Edit in a dialog. */
function Records({
  resource,
  itemLabel,
  columns,
  params,
  defaults,
  hidden = [],
  extra,
  transform,
  onRowClick,
}: RecordsProps) {
  const [editing, setEditing] = useState<Editing | null>(null);
  const fields = Object.fromEntries(hidden.map((name) => [name, { hidden: true }]));
  return (
    <>
      <ResourceTable
        resource={resource}
        itemLabel={itemLabel}
        columns={columns}
        params={params}
        syncUrl={false}
        onCreate={() => setEditing({ id: null })}
        onEdit={(row) => setEditing({ id: String(row["id"]) })}
        onRowClick={onRowClick}
        enableDelete
      />
      <Modal
        title={editing?.id ? `Edit the ${itemLabel}` : `New ${itemLabel}`}
        open={editing !== null}
        onOpenChange={(open) => {
          if (!open) setEditing(null);
        }}
      >
        {editing !== null ? (
          <ResourceForm
            key={editing.id ?? "new"}
            resource={resource}
            id={editing.id ?? undefined}
            defaultValues={editing.id ? undefined : defaults}
            fields={fields}
            extraFields={extra?.(editing.id)}
            transformSubmit={(values) => {
              const merged = { ...defaults, ...values };
              return transform ? transform(merged) : merged;
            }}
            onSuccess={() => setEditing(null)}
          />
        ) : null}
      </Modal>
    </>
  );
}

function Chips({
  values,
  onRemove,
  label,
}: {
  values: readonly NamedKey[];
  onRemove: (key: string) => void;
  label: string;
}) {
  if (values.length === 0) return <p className="text-sm text-muted-foreground">None: any.</p>;
  return (
    <ul className="flex flex-wrap gap-2" aria-label={label}>
      {values.map((value) => (
        <li
          key={value.key}
          className="flex items-center gap-1 rounded-full border border-border px-2 py-0.5 text-sm"
        >
          {value.name}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-6 px-1"
            onClick={() => onRemove(value.key)}
          >
            <span aria-hidden="true">×</span>
            <span className="sr-only">Remove {value.name}</span>
          </Button>
        </li>
      ))}
    </ul>
  );
}

/** Search, then pick: results as buttons, the picked ones as chips. */
function Picker({
  label,
  values,
  onChange,
  results,
  search,
  onSearch,
}: {
  label: string;
  values: readonly NamedKey[];
  onChange: (values: NamedKey[]) => void;
  results: readonly NamedKey[];
  search: string;
  onSearch: (text: string) => void;
}) {
  const id = useId();
  const picked = new Set(values.map((value) => value.key));
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium">{label}</legend>
      <Chips
        values={values}
        label={label}
        onRemove={(key) => onChange(values.filter((value) => value.key !== key))}
      />
      <Label htmlFor={id} className="sr-only">
        Find {label.toLowerCase()}
      </Label>
      <Input
        id={id}
        type="search"
        placeholder={`Find ${label.toLowerCase()}`}
        value={search}
        onChange={(event) => onSearch(event.target.value)}
      />
      {search.trim() ? (
        <ul className="max-h-40 space-y-1 overflow-y-auto">
          {results
            .filter((result) => !picked.has(result.key))
            .map((result) => (
              <li key={result.key}>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="w-full justify-start"
                  onClick={() => {
                    onChange([...values, result]);
                    onSearch("");
                  }}
                >
                  Add {result.name}
                </Button>
              </li>
            ))}
        </ul>
      ) : null}
    </fieldset>
  );
}

function useTyped(): [string, string, (text: string) => void] {
  const [typed, setTyped] = useState("");
  const [search, setSearch] = useState("");
  useEffect(() => {
    const wait = setTimeout(() => setSearch(typed.trim()), 250);
    return () => clearTimeout(wait);
  }, [typed]);
  return [typed, search, setTyped];
}

function ItemsPicker({
  values,
  onChange,
}: {
  values: NamedKey[];
  onChange: (values: NamedKey[]) => void;
}) {
  const client = useKarniClient();
  const [typed, search, setTyped] = useTyped();
  const found = useQuery<SellableItem[]>({
    queryKey: ["karni-commerce", "items", "", search],
    enabled: search !== "",
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) =>
      client.request<SellableItem[]>("/orders/items/", { query: { search }, signal }),
  });
  const seen = new Set<string>();
  const results: NamedKey[] = [];
  for (const item of found.data ?? []) {
    const key = `${item.kind}:${item.item}`;
    if (seen.has(key)) continue;
    seen.add(key);
    results.push({ key, name: item.name });
  }
  return (
    <Picker
      label="Items"
      values={values}
      onChange={onChange}
      results={results}
      search={typed}
      onSearch={setTyped}
    />
  );
}

function LimitPicker({
  limit,
  values,
  onChange,
}: {
  limit: CouponLimit;
  values: NamedKey[];
  onChange: (values: NamedKey[]) => void;
}) {
  const [typed, search, setTyped] = useTyped();
  const found = useResourceList<Row>(
    limit.resource,
    { search, pageSize: 10 },
    { enabled: search !== "" },
  );
  const field = limit.labelField ?? "name";
  const results = (found.data?.results ?? []).map((row) => ({
    key: String(row["id"]),
    name: String(row[field] ?? row["id"]),
  }));
  return (
    <Picker
      label={limit.label}
      values={values}
      onChange={onChange}
      results={results}
      search={typed}
      onSearch={setTyped}
    />
  );
}

/** What a coupon applies to, kept beside its form until it is saved. */
function useCouponLimits() {
  const [items, setItems] = useState<NamedKey[]>([]);
  const [limits, setLimits] = useState<Record<string, NamedKey[]>>({});
  return { items, setItems, limits, setLimits };
}

function CouponLimitsFields({
  id,
  state,
}: {
  id: string | null;
  state: ReturnType<typeof useCouponLimits>;
}) {
  const row = useResourceItem<Row>("coupons", id ?? "", undefined, { enabled: id !== null });
  const { setItems, setLimits } = state;
  useEffect(() => {
    if (id === null) {
      setItems([]);
      setLimits({});
      return;
    }
    if (!row.data) return;
    setItems(named(row.data["items"]));
    const stored = (row.data["limits"] ?? {}) as Record<string, unknown>;
    setLimits(Object.fromEntries(Object.entries(stored).map(([key, v]) => [key, named(v)])));
  }, [id, row.data, setItems, setLimits]);
  return (
    <div className="space-y-4 rounded-md border border-border p-3">
      <p className="text-sm text-muted-foreground">
        What it applies to. Leave both empty for everything.
      </p>
      <ItemsPicker values={state.items} onChange={state.setItems} />
      {couponLimits().map((limit) => (
        <LimitPicker
          key={limit.key}
          limit={limit}
          values={state.limits[limit.key] ?? []}
          onChange={(values) => state.setLimits({ ...state.limits, [limit.key]: values })}
        />
      ))}
    </div>
  );
}

const COUPON_COLUMNS: ReadonlyArray<ResourceColumn> = [
  { field: "code" },
  { field: "description" },
  { field: "kind" },
  { field: "amount" },
  { field: "minimum_spend", header: "Minimum spend" },
  { field: "ends_at", header: "Ends" },
  { field: "usage_limit", header: "Uses allowed" },
  { field: "active" },
];

export interface SettingsPageProps {
  title?: string;
}

/** Coupons: percent, amount or free shipping, with their rules and limits. */
export function CouponsPage({ title = "Coupons" }: SettingsPageProps) {
  const state = useCouponLimits();
  return (
    <Page
      title={title}
      description="Codes a customer types at the cart or at checkout. Each use is counted on its order."
    >
      <Records
        resource="coupons"
        itemLabel="coupon"
        columns={COUPON_COLUMNS}
        hidden={["items", "limits"]}
        defaults={{ kind: "percent", active: true }}
        extra={(id) => <CouponLimitsFields id={id} state={state} />}
        transform={(values) => ({
          ...values,
          items: state.items,
          limits: Object.fromEntries(
            Object.entries(state.limits).filter(([, chosen]) => chosen.length > 0),
          ),
        })}
      />
    </Page>
  );
}

const ZONE_COLUMNS: ReadonlyArray<ResourceColumn> = [
  { field: "name" },
  { field: "countries" },
  { field: "regions" },
  { field: "position", header: "Order" },
];

const METHOD_COLUMNS: ReadonlyArray<ResourceColumn> = [
  { field: "name" },
  { field: "kind" },
  { field: "cost" },
  { field: "free_above", header: "Free above" },
  { field: "taxable" },
  { field: "active" },
];

/** Shipping zones (where) and each zone's methods (how, and for how much). */
export function ShippingPage({ title = "Shipping" }: SettingsPageProps) {
  const [zone, setZone] = useState<{ id: string; name: string } | null>(null);
  return (
    <Page
      title={title}
      description="Checkout offers the methods of the first zone that covers the address. A zone with no countries covers everywhere else."
    >
      <Records
        resource="shipping-zones"
        itemLabel="zone"
        columns={ZONE_COLUMNS}
        onRowClick={(row) => setZone({ id: String(row["id"]), name: String(row["name"]) })}
      />
      {zone !== null ? (
        <section className="mt-8 space-y-3" aria-label={`Methods of ${zone.name}`}>
          <h2 className="text-lg font-semibold">Methods of {zone.name}</h2>
          <Records
            key={zone.id}
            resource="shipping-methods"
            itemLabel="method"
            columns={METHOD_COLUMNS}
            params={{ zone: zone.id }}
            defaults={{ zone: zone.id, kind: "flat", active: true, taxable: true }}
            hidden={["zone"]}
          />
        </section>
      ) : (
        <p className="mt-6 text-sm text-muted-foreground">
          Open a zone to see and change its methods.
        </p>
      )}
    </Page>
  );
}

const RATE_COLUMNS: ReadonlyArray<ResourceColumn> = [
  { field: "name" },
  { field: "country" },
  { field: "region" },
  { field: "rate", header: "Rate (%)" },
  { field: "tax_class", header: "Tax class" },
  { field: "shipping", header: "On shipping" },
];

/** Tax rates by country and region. The most specific rate wins. */
export function TaxRatesPage({ title = "Tax rates" }: SettingsPageProps) {
  return (
    <Page
      title={title}
      description="The rate of an address: its country and region, else its country, else the rate with neither."
    >
      <Records resource="tax-rates" itemLabel="tax rate" columns={RATE_COLUMNS} />
    </Page>
  );
}
