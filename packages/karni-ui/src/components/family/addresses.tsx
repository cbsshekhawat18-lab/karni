/**
 * `<MyAddresses>`: the signed-in person's saved addresses
 * (karni.people, `/people-addresses/`), for their account page: each one,
 * which is the default for shipping and billing, add one, and remove one.
 *
 * The list answers the person's own addresses through the role's `own`
 * grant on `people.address` (the family's `customer` role holds it while
 * the people contract is on). A person not linked to an account yet (an
 * email not verified) is told so instead.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { KarniApiError } from "../../schema/client";
import { useKarniClient } from "../../schema/provider";
import { ErrorState } from "../../states/ErrorState";
import { PendingButton } from "../../states/PendingButton";
import { Button } from "../primitives/button";
import { Input } from "../primitives/input";
import { Label } from "../primitives/label";
import { Skeleton } from "../primitives/skeleton";
import { useToast } from "../toast/use-toast";

interface Address extends Record<string, unknown> {
  id: string;
  label: string;
  line1: string;
  line2: string;
  city: string;
  region: string;
  postcode: string;
  country: string;
  is_default_billing: boolean;
  is_default_shipping: boolean;
}

const KEY = ["karni", "people-addresses", "$mine"] as const;
const FIELDS = [
  { name: "label", label: "Label (home, work)" },
  { name: "line1", label: "Address" },
  { name: "city", label: "City" },
  { name: "postcode", label: "Postcode" },
  { name: "country", label: "Country (two letters)" },
] as const;

function text(row: Address): string {
  return [row.line1, row.line2, row.city, row.region, row.postcode, row.country]
    .filter((part) => part)
    .join(", ");
}

function errorsOf(error: unknown): Record<string, string> {
  if (!(error instanceof KarniApiError) || typeof error.data !== "object" || error.data === null) {
    return {};
  }
  const found: Record<string, string> = {};
  for (const [name, value] of Object.entries(error.data as Record<string, unknown>)) {
    found[name] = Array.isArray(value) ? value.map(String).join(" ") : String(value);
  }
  return found;
}

/** The signed-in person's addresses, to add and remove. */
export function MyAddresses(): React.ReactElement {
  const client = useKarniClient();
  const queryClient = useQueryClient();
  const { success, error: toastError } = useToast();
  const prefix = React.useId();
  const [adding, setAdding] = React.useState(false);
  const [draft, setDraft] = React.useState<Record<string, string>>({});
  const me = useQuery({
    queryKey: ["karni", "people", "$me"],
    retry: false,
    queryFn: ({ signal }) => client.request<{ id: string }>("/people/me/", { signal }),
  });
  const list = useQuery({
    queryKey: KEY,
    enabled: me.isSuccess,
    retry: false,
    queryFn: ({ signal }) =>
      client.request<{ results: Address[] }>("/people-addresses/", {
        signal,
        query: { page_size: "50" },
      }),
  });
  const add = useMutation({
    mutationFn: () =>
      client.request<Address>("/people-addresses/", {
        method: "POST",
        body: { ...draft, person: me.data?.id, country: (draft["country"] ?? "").toUpperCase() },
      }),
    onSuccess: async () => {
      setDraft({});
      setAdding(false);
      success("The address is saved");
      await queryClient.invalidateQueries({ queryKey: KEY });
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => client.request(`/people-addresses/${id}/`, { method: "DELETE" }),
    onSuccess: async () => {
      success("The address is removed");
      await queryClient.invalidateQueries({ queryKey: KEY });
    },
    onError: () => toastError("The address was not removed", { description: "Try again." }),
  });
  if (me.isPending || (me.isSuccess && list.isPending)) return <Skeleton className="h-16 w-full" />;
  if (me.error instanceof KarniApiError && me.error.status === 404) {
    return (
      <p className="text-sm text-muted-foreground">
        Your addresses show here once your email is verified.
      </p>
    );
  }
  if (me.isError || list.isError) {
    return (
      <ErrorState
        variant="inline"
        error={me.error ?? list.error}
        context={{ action: "view", resource: "addresses" }}
        onRetry={() => void (me.isError ? me.refetch() : list.refetch())}
      />
    );
  }
  const rows = list.data?.results ?? [];
  const errors = errorsOf(add.error);
  return (
    <div className="space-y-4">
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">No saved address yet.</p>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {rows.map((row) => (
            <li key={row.id} className="space-y-2 rounded-md border border-border p-3 text-sm">
              <p className="font-medium">
                {row.label || "Address"}
                {row.is_default_shipping ? " · shipping" : ""}
                {row.is_default_billing ? " · billing" : ""}
              </p>
              <p>{text(row)}</p>
              <Button
                variant="ghost"
                size="sm"
                aria-label={`Remove ${row.label || text(row)}`}
                disabled={remove.isPending}
                onClick={() => remove.mutate(row.id)}
              >
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}
      {adding ? (
        <form
          className="grid max-w-128 gap-3 sm:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault();
            add.mutate();
          }}
        >
          {FIELDS.map((field) => {
            const id = `${prefix}-${field.name}`;
            const message = errors[field.name];
            return (
              <div key={field.name} className="space-y-1">
                <Label htmlFor={id}>{field.label}</Label>
                <Input
                  id={id}
                  value={draft[field.name] ?? ""}
                  aria-invalid={message !== undefined || undefined}
                  aria-describedby={message !== undefined ? `${id}-error` : undefined}
                  onChange={(event) => setDraft({ ...draft, [field.name]: event.target.value })}
                />
                {message !== undefined ? (
                  <p id={`${id}-error`} role="alert" className="text-sm text-destructive">
                    {message}
                  </p>
                ) : null}
              </div>
            );
          })}
          <div className="flex flex-wrap gap-2 sm:col-span-2">
            <PendingButton type="submit" pending={add.isPending}>
              Save the address
            </PendingButton>
            <Button type="button" variant="outline" onClick={() => setAdding(false)}>
              Cancel
            </Button>
          </div>
          {add.isError && Object.keys(errors).length === 0 ? (
            <p role="alert" className="text-sm text-destructive sm:col-span-2">
              The address was not saved. Try again.
            </p>
          ) : null}
        </form>
      ) : (
        <Button variant="outline" onClick={() => setAdding(true)}>
          Add an address
        </Button>
      )}
    </div>
  );
}
