/**
 * Experimental. The staff side of "one person" (karni.people):
 *
 * - `<PeoplePage>`: `/people`, every person the caller's grants reach, with
 *   search, sorting, paging and a column per person fact the installed
 *   parts contribute (orders, total spent, next booking), sorted in SQL.
 *   `label` names the list ("Customers" in a shop alone) and `filters`
 *   narrows it (`{ orders__gte: "1" }`: people who bought).
 * - `<PersonPage>`: `/people/<id>`, the person's details, addresses and
 *   organisations, their facts, a tab per installed part
 *   (`registerPersonTab`: the shop's orders, the bookings) and the
 *   `<Timeline>` with the person's change history next to it. Merge and
 *   Erase show only to who holds `people.person:merge` and
 *   `people.person:erase` (the person's `can`), and the server checks them
 *   again.
 *
 * Escape hatch: `tabs` replaces the registered tabs on one page, and the
 * hooks under them are the plain API (`/people/`, `/people/facts/`).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as React from "react";
import { useAuth } from "../../auth/provider";
import { karniKeys } from "../../hooks/keys";
import { usePageMeta } from "../../hooks/usePageMeta";
import { formatMoney } from "../../lib/money";
import { KarniApiError } from "../../schema/client";
import { useKarniClient } from "../../schema/provider";
import { ErrorState } from "../../states/ErrorState";
import { PendingButton } from "../../states/PendingButton";
import { EmptyState } from "../empty-state/empty-state";
import { Modal, ModalClose } from "../modal/modal";
import { Page } from "../page/page";
import { Button } from "../primitives/button";
import { Input } from "../primitives/input";
import { Label } from "../primitives/label";
import { Skeleton } from "../primitives/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../primitives/tabs";
import { ResourceTable, type ResourceColumn } from "../resource/ResourceTable";
import { useToast } from "../toast/use-toast";
import { Stat } from "../stat/stat";
import { useBusiness } from "./audience";
import { personTabs, type PersonTab } from "./registry";
import { Timeline } from "./timeline";

/** Experimental. One person fact a part contributes (`GET /people/facts/`). */
export interface PersonFact {
  name: string;
  label: string;
  /** count, number, money, date, datetime, boolean or text. */
  kind: string;
  source: string;
  description: string;
}

/** Experimental. The person facts the installed parts contribute. */
export function usePersonFacts() {
  const client = useKarniClient();
  return useQuery<PersonFact[]>({
    queryKey: ["karni", "people", "$facts"],
    staleTime: 10 * 60 * 1000,
    retry: false,
    queryFn: ({ signal }) => client.request<PersonFact[]>("/people/facts/", { signal }),
  });
}

/** Experimental. A fact's value in words, by its kind (money in the business's currency). */
export function factText(fact: PersonFact, value: unknown, currency: string): string {
  if (value === null || value === undefined || value === "") return "–";
  switch (fact.kind) {
    case "money":
      return currency !== "" ? formatMoney(String(value), currency) : String(value);
    case "date":
    case "datetime": {
      const date = new Date(String(value));
      if (Number.isNaN(date.getTime())) return String(value);
      return fact.kind === "date"
        ? date.toLocaleDateString()
        : date.toLocaleDateString(undefined, { dateStyle: "medium" });
    }
    case "boolean":
      return value === true ? "Yes" : "No";
    case "count":
    case "number": {
      const number = Number(value);
      return Number.isFinite(number) ? number.toLocaleString() : String(value);
    }
    default:
      return String(value);
  }
}

const HIDDEN_PERSON_FIELDS = [
  "given_name",
  "family_name",
  "user",
  "time_zone",
  "language",
  "source",
  "merged_into",
  "erased_at",
];

export interface PeoplePageProps {
  /** The page's heading: "People", or "Customers" in a shop alone. */
  label?: string;
  /** A line under the heading. */
  description?: string;
  /** Pinned list filters (`{ orders__gte: "1" }`). */
  filters?: Record<string, string>;
  /** The facts shown as columns (default: every fact, at most `maxFacts`). */
  facts?: readonly string[];
  /** The most fact columns when `facts` is not given. Default 4. */
  maxFacts?: number;
  /** Opens a person's page. */
  navigate: (to: string) => void;
  /** Where a person's page is (default `/people/<id>`). */
  personHref?: (id: string) => string;
  siteName?: string;
}

/** Experimental. `/people`: the people the caller may read, with the facts of every installed part. */
export function PeoplePage({
  label = "People",
  description,
  filters,
  facts,
  maxFacts = 4,
  navigate,
  personHref = (id) => `/people/${id}`,
  siteName,
}: PeoplePageProps): React.ReactElement {
  usePageMeta({ title: label, siteName });
  const known = usePersonFacts();
  const currency = useBusiness().data?.currency ?? "";
  const shown = React.useMemo(() => {
    const all = known.data ?? [];
    return facts !== undefined
      ? all.filter((fact) => facts.includes(fact.name))
      : all.slice(0, maxFacts);
  }, [known.data, facts, maxFacts]);
  const columns = React.useMemo<ReadonlyArray<ResourceColumn>>(
    () => [
      { field: "display_name", header: "Name" },
      ...HIDDEN_PERSON_FIELDS.map((field) => ({ field, hidden: true })),
      ...shown.map((fact) => ({
        field: fact.name,
        header: fact.label,
        sortable: true,
        cell: (row: Record<string, unknown>) =>
          factText(
            fact,
            (row["facts"] as Record<string, unknown> | undefined)?.[fact.name],
            currency,
          ),
      })),
    ],
    [shown, currency],
  );
  const params = React.useMemo(
    () => ({
      ...(filters ?? {}),
      ...(shown.length > 0 ? { facts: shown.map((fact) => fact.name).join(",") } : {}),
    }),
    [filters, shown],
  );
  if (known.isPending) {
    return (
      <Page title={label} description={description}>
        <Skeleton className="h-64 w-full" />
      </Page>
    );
  }
  return (
    <Page title={label} description={description}>
      <ResourceTable
        resource="people"
        columns={columns}
        params={params}
        caption={label}
        resourceLabel={label.toLowerCase()}
        itemLabel={label === "Customers" ? "customer" : "person"}
        importable={false}
        filters={["organisation"]}
        onRowClick={(row) => navigate(personHref(String(row["id"])))}
      />
    </Page>
  );
}

interface PersonBody extends Record<string, unknown> {
  id: string;
  display_name: string;
  email: string;
  phone: string;
  facts?: Record<string, unknown>;
  can?: { merge: boolean; erase: boolean };
}

interface Paged<T> {
  count: number;
  results: T[];
}

interface MergePlan {
  keep: string;
  drop: string;
  allowed: boolean;
  moves: Array<{ model: string; field: string; kind: string; rows: number }>;
  refusals: Array<{ code: string; message: string }>;
  fills: Record<string, unknown>;
}

function addressText(row: Record<string, unknown>): string {
  return ["line1", "line2", "city", "region", "postcode", "country"]
    .map((name) => String(row[name] ?? "").trim())
    .filter((part) => part !== "")
    .join(", ");
}

function relationName(value: unknown): string {
  if (value !== null && typeof value === "object") {
    const row = value as Record<string, unknown>;
    return String(row["name"] ?? row["display_name"] ?? row["id"] ?? "");
  }
  return String(value ?? "");
}

function Details({ person }: { person: PersonBody }): React.ReactElement {
  const client = useKarniClient();
  const addresses = useQuery({
    queryKey: [...karniKeys.resource("people-addresses"), "of", person.id],
    retry: false,
    queryFn: ({ signal }) =>
      client.request<Paged<Record<string, unknown>>>("/people-addresses/", {
        signal,
        query: { person: person.id, page_size: "50" },
      }),
  });
  const memberships = useQuery({
    queryKey: [...karniKeys.resource("people-memberships"), "of", person.id],
    retry: false,
    queryFn: ({ signal }) =>
      client.request<Paged<Record<string, unknown>>>("/people-memberships/", {
        signal,
        query: { person: person.id, expand: "organisation", page_size: "50" },
      }),
  });
  return (
    <div className="grid gap-8 md:grid-cols-2">
      <section aria-labelledby="person-addresses" className="space-y-2">
        <h2 id="person-addresses" className="text-lg font-semibold">
          Addresses
        </h2>
        {addresses.isPending ? (
          <Skeleton className="h-12 w-full" />
        ) : addresses.isError ? (
          <ErrorState
            variant="inline"
            error={addresses.error}
            context={{ action: "view", resource: "addresses" }}
            onRetry={() => void addresses.refetch()}
          />
        ) : addresses.data.results.length === 0 ? (
          <p className="text-sm text-muted-foreground">No address yet.</p>
        ) : (
          <ul className="space-y-2">
            {addresses.data.results.map((row) => (
              <li key={String(row["id"])} className="rounded-md border border-border p-3 text-sm">
                <p className="font-medium">
                  {String(row["label"] || "Address")}
                  {row["is_default_shipping"] === true ? " · shipping" : ""}
                  {row["is_default_billing"] === true ? " · billing" : ""}
                </p>
                <p>{addressText(row)}</p>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section aria-labelledby="person-organisations" className="space-y-2">
        <h2 id="person-organisations" className="text-lg font-semibold">
          Organisations
        </h2>
        {memberships.isPending ? (
          <Skeleton className="h-12 w-full" />
        ) : memberships.isError ? (
          <ErrorState
            variant="inline"
            error={memberships.error}
            context={{ action: "view", resource: "organisations" }}
            onRetry={() => void memberships.refetch()}
          />
        ) : memberships.data.results.length === 0 ? (
          <p className="text-sm text-muted-foreground">Not a member of any organisation.</p>
        ) : (
          <ul className="space-y-2 text-sm">
            {memberships.data.results.map((row) => (
              <li key={String(row["id"])}>
                <span className="font-medium">{relationName(row["organisation"])}</span>
                {row["title"] ? `, ${String(row["title"])}` : ""}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function MergeDialog({
  person,
  open,
  onOpenChange,
  onMerged,
}: {
  person: PersonBody;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onMerged: () => void;
}): React.ReactElement {
  const client = useKarniClient();
  const searchId = React.useId();
  const [search, setSearch] = React.useState("");
  const [drop, setDrop] = React.useState<PersonBody | null>(null);
  const found = useQuery({
    queryKey: ["karni", "people", "$merge-candidates", person.id, search],
    enabled: open && search.trim().length >= 2,
    retry: false,
    queryFn: ({ signal }) =>
      client.request<Paged<PersonBody>>("/people/", {
        signal,
        query: { search: search.trim(), page_size: "8" },
      }),
  });
  const plan = useQuery({
    queryKey: ["karni", "people", "$merge-plan", person.id, drop?.id ?? null],
    enabled: drop !== null,
    retry: false,
    queryFn: ({ signal }) =>
      client.request<MergePlan>(`/people/${person.id}/merge-plan/`, {
        signal,
        query: { drop: drop?.id ?? "" },
      }),
  });
  const merge = useMutation({
    mutationFn: () =>
      client.request<MergePlan>(`/people/${person.id}/merge/`, {
        method: "POST",
        body: { drop: drop?.id },
      }),
    onSuccess: () => {
      setDrop(null);
      setSearch("");
      onMerged();
    },
  });
  const candidates = (found.data?.results ?? []).filter((row) => row.id !== person.id);
  return (
    <Modal
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          setDrop(null);
          merge.reset();
        }
        onOpenChange(next);
      }}
      title={`Merge another record into ${person.display_name || person.email}`}
      description="Everything the other record holds moves here: orders, bookings, notes, the timeline. The other record is then removed."
      footer={
        <>
          <ModalClose asChild>
            <Button variant="outline">Cancel</Button>
          </ModalClose>
          <PendingButton
            pending={merge.isPending}
            disabled={drop === null || plan.data?.allowed !== true}
            onClick={() => merge.mutate()}
          >
            Merge
          </PendingButton>
        </>
      }
    >
      <div className="space-y-4">
        {drop === null ? (
          <div className="space-y-2">
            <Label htmlFor={searchId}>Find the other record</Label>
            <Input
              id={searchId}
              type="search"
              value={search}
              placeholder="A name or an email"
              onChange={(event) => setSearch(event.target.value)}
            />
            {candidates.length > 0 ? (
              <ul className="rounded-md border border-border [&>*+*]:border-t [&>*+*]:border-border">
                {candidates.map((row) => (
                  <li key={row.id}>
                    <button
                      type="button"
                      className="w-full px-3 py-2 text-left text-sm hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      onClick={() => setDrop(row)}
                    >
                      <span className="font-medium">{row.display_name || row.email}</span>
                      {row.email ? (
                        <span className="block text-muted-foreground">{row.email}</span>
                      ) : null}
                    </button>
                  </li>
                ))}
              </ul>
            ) : search.trim().length >= 2 && found.isSuccess ? (
              <p className="text-sm text-muted-foreground">Nobody else matches.</p>
            ) : null}
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-sm">
              Merging <span className="font-medium">{drop.display_name || drop.email}</span> into
              this record.{" "}
              <Button variant="link" size="sm" onClick={() => setDrop(null)}>
                Choose another
              </Button>
            </p>
            {plan.isPending ? (
              <Skeleton className="h-16 w-full" />
            ) : plan.isError ? (
              <ErrorState variant="inline" error={plan.error} context={{ action: "view" }} />
            ) : plan.data.refusals.length > 0 ? (
              <ul role="alert" className="space-y-1 text-sm text-destructive">
                {plan.data.refusals.map((refusal) => (
                  <li key={refusal.code + refusal.message}>{refusal.message}</li>
                ))}
              </ul>
            ) : (
              <ul className="space-y-1 text-sm">
                {plan.data.moves.length === 0 ? <li>Nothing else points at it.</li> : null}
                {plan.data.moves.map((move) => (
                  <li key={`${move.model}.${move.field}`}>
                    {move.rows} {move.model.split(".").pop()} {move.rows === 1 ? "row" : "rows"}{" "}
                    move here
                  </li>
                ))}
                {Object.keys(plan.data.fills).length > 0 ? (
                  <li>Fills in: {Object.keys(plan.data.fills).join(", ").replace(/_/g, " ")}</li>
                ) : null}
              </ul>
            )}
            {merge.isError ? (
              <p role="alert" className="text-sm text-destructive">
                {merge.error instanceof KarniApiError && merge.error.status === 409
                  ? "The merge was refused. Look at the reasons above."
                  : "The merge did not go through. Try again."}
              </p>
            ) : null}
          </div>
        )}
      </div>
    </Modal>
  );
}

function EraseDialog({
  person,
  open,
  onOpenChange,
  onErased,
}: {
  person: PersonBody;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onErased: () => void;
}): React.ReactElement {
  const client = useKarniClient();
  const erase = useMutation({
    mutationFn: () => client.request<null>(`/people/${person.id}/erase/`, { method: "POST" }),
    onSuccess: onErased,
  });
  const name = person.display_name || person.email || "this person";
  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={`Erase ${name}'s data?`}
      description="Their name, email, phone and addresses go, in every part. Orders keep their amounts and numbers without the name. This cannot be undone."
      footer={
        <>
          <ModalClose asChild>
            <Button variant="outline">Cancel</Button>
          </ModalClose>
          <PendingButton
            variant="destructive"
            pending={erase.isPending}
            onClick={() => erase.mutate()}
          >
            Erase the data
          </PendingButton>
        </>
      }
    >
      {erase.isError ? (
        <p role="alert" className="text-sm text-destructive">
          The data was not erased. Try again.
        </p>
      ) : (
        <p className="text-sm">Do this when the person asks for their data to be deleted.</p>
      )}
    </Modal>
  );
}

export interface PersonPageProps {
  /** The person's id. */
  id: string;
  /** Opens an app path (back to the list, a record of a tab). */
  navigate: (to: string) => void;
  /** The list this page belongs to (default "/people"). */
  listHref?: string;
  /** The list's name, for the back link ("Customers"). Default "People". */
  listLabel?: string;
  /** The tabs instead of the registered ones. */
  tabs?: readonly PersonTab[];
  /** Where a timeline entry's record opens. */
  hrefFor?: (resource: string, id: string, row: Readonly<Record<string, unknown>>) => string | null;
  siteName?: string;
}

/** Experimental. `/people/<id>`: one person across every installed part. */
export function PersonPage({
  id,
  navigate,
  listHref = "/people",
  listLabel = "People",
  tabs,
  hrefFor,
  siteName,
}: PersonPageProps): React.ReactElement {
  const client = useKarniClient();
  const queryClient = useQueryClient();
  const { roles } = useAuth();
  const { success } = useToast();
  const facts = usePersonFacts();
  const currency = useBusiness().data?.currency ?? "";
  const [merging, setMerging] = React.useState(false);
  const [erasing, setErasing] = React.useState(false);
  const person = useQuery({
    queryKey: [...karniKeys.detail("people", id), "$page"],
    retry: false,
    queryFn: ({ signal }) =>
      client.request<PersonBody>(`/people/${id}/`, { signal, query: { facts: "all" } }),
  });
  const name = person.data ? person.data.display_name || person.data.email || "Person" : "Person";
  usePageMeta({ title: name, siteName });
  const back = (
    <Button variant="outline" onClick={() => navigate(listHref)}>
      Back to {listLabel.toLowerCase()}
    </Button>
  );
  if (person.isPending) {
    return (
      <Page title={<Skeleton className="h-8 w-48" />}>
        <Skeleton className="h-40 w-full" />
      </Page>
    );
  }
  if (person.isError) {
    const missing = person.error instanceof KarniApiError && person.error.status === 404;
    return (
      <Page title={missing ? "Couldn't find this person" : "Person"}>
        {missing ? (
          <EmptyState
            title="Nobody here"
            description="This person does not exist, was merged into another record, or is not one you may see."
            action={back}
          />
        ) : (
          <ErrorState
            error={person.error}
            context={{ action: "view", resource: "person" }}
            onRetry={() => void person.refetch()}
            actions={back}
          />
        )}
      </Page>
    );
  }
  const data = person.data;
  const shownTabs = (tabs ?? personTabs()).filter(
    (tab) => !tab.roles || tab.roles.some((role) => roles.includes(role)),
  );
  const known = facts.data ?? [];
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["karni"] });
  return (
    <Page
      title={name}
      description={[data.email, data.phone].filter((part) => part).join(" · ") || undefined}
      actions={
        <div className="flex flex-wrap gap-2">
          {back}
          {data.can?.merge === true ? (
            <Button variant="outline" onClick={() => setMerging(true)}>
              Merge
            </Button>
          ) : null}
          {data.can?.erase === true ? (
            <Button variant="destructive" onClick={() => setErasing(true)}>
              Erase
            </Button>
          ) : null}
        </div>
      }
    >
      {known.length > 0 ? (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4" aria-label="Facts" role="group">
          {known.map((fact) => (
            <Stat
              key={fact.name}
              label={fact.label}
              value={factText(fact, data.facts?.[fact.name], currency)}
            />
          ))}
        </div>
      ) : null}
      <Tabs defaultValue="timeline">
        <div className="max-w-full overflow-x-auto">
          <TabsList aria-label="About this person">
            <TabsTrigger value="timeline">Timeline</TabsTrigger>
            <TabsTrigger value="details">Details</TabsTrigger>
            {shownTabs.map((tab) => (
              <TabsTrigger key={tab.key} value={`part-${tab.key}`}>
                {tab.title}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
        <TabsContent value="timeline" className="pt-4">
          <Timeline
            person={id}
            history={{ resource: "people", id }}
            navigate={navigate}
            title={null}
            {...(hrefFor !== undefined ? { hrefFor } : {})}
          />
        </TabsContent>
        <TabsContent value="details" className="pt-4">
          <Details person={data} />
        </TabsContent>
        {shownTabs.map((tab) => (
          <TabsContent key={tab.key} value={`part-${tab.key}`} className="pt-4">
            <tab.component personId={id} person={data} navigate={navigate} />
          </TabsContent>
        ))}
      </Tabs>
      {data.can?.merge === true ? (
        <MergeDialog
          person={data}
          open={merging}
          onOpenChange={setMerging}
          onMerged={() => {
            setMerging(false);
            success("Merged");
            refresh();
          }}
        />
      ) : null}
      {data.can?.erase === true ? (
        <EraseDialog
          person={data}
          open={erasing}
          onOpenChange={setErasing}
          onErased={() => {
            setErasing(false);
            success("The person's data is erased");
            refresh();
            navigate(listHref);
          }}
        />
      ) : null}
    </Page>
  );
}
