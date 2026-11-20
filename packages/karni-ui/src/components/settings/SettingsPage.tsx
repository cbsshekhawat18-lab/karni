/**
 * Experimental. The one Settings page of a project, built on the preferences
 * contract's `GET /preferences/` (karni.preferences): the details of the
 * business, one tab for each settings section a part declares, the emails the
 * project sends (each with its switch, and an editor for the ones the business
 * may rewrite), and the connections between the parts installed together.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type ReactNode } from "react";
import { usePageMeta } from "../../hooks/usePageMeta";
import { cn } from "../../lib/cn";
import { KarniApiError } from "../../schema/client";
import { useKarniClient } from "../../schema/provider";
import { PendingButton } from "../../states/PendingButton";
import { EmptyState } from "../empty-state/empty-state";
import { Button } from "../primitives/button";
import { Input } from "../primitives/input";
import { Label } from "../primitives/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../primitives/tabs";
import { Textarea } from "../primitives/textarea";
import { useToast } from "../toast/use-toast";
import { EmailTemplateEditor } from "./EmailTemplateEditor";
import { readFormErrors, type FormErrors } from "./errors";

export interface SettingsPageProps {
  /** The page's heading and title. */
  title?: string;
  /** The site's name, after the title in the browser tab. */
  siteName?: string;
}

interface DetailField {
  name: string;
  label: string;
  type: "text" | "textarea" | "email" | "choice" | "file";
  help?: string;
  choices?: { value: string; label: string }[];
}

interface Details {
  values: Record<string, unknown>;
  fields: DetailField[];
  locked: string[];
  can_change: boolean;
}

interface SchemaProperty {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  minimum?: number;
  maximum?: number;
  maxLength?: number;
  enum?: unknown[];
}

interface Section {
  key: string;
  title: string;
  describe: string;
  version: number;
  schema: { properties?: Record<string, SchemaProperty> };
  values: Record<string, unknown>;
  defaults: Record<string, unknown>;
  locked: string[];
  can_change: boolean;
}

interface EmailItem {
  name: string;
  title: string;
  describe: string;
  /** Who gets it ("the buyer"). Blank for an email declared without one. */
  audience?: string;
  transactional: boolean;
  /** False: it always goes out (a sign-in code). */
  switchable?: boolean;
  /** The business may rewrite its text (/email-templates/<kind>/). */
  editable?: boolean;
  source: string;
  default: boolean;
  on: boolean;
  locked: boolean;
}

interface ConnectionItem {
  name: string;
  title: string;
  describe: string;
  part: string;
  needs: string[];
  installed: boolean;
  default: boolean;
  on: boolean;
  active: boolean;
  locked: boolean;
}

interface Preferences {
  contract: number;
  details: Details;
  sections: Section[];
  connections: { items: ConnectionItem[]; can_change: boolean };
  emails: {
    sender: { sender_name: string; sender_email: string; reply_to: string; from: string };
    items: EmailItem[];
    can_change: boolean;
  };
}

const PREFERENCES_KEY = ["karni", "preferences"];
/** The heading of a group of emails, by the prefix of their names (commerce.order_paid). */
const GROUP_TITLES: Record<string, string> = {
  commerce: "Orders",
  shop: "Shop",
  accounts: "Accounts",
};
const CONTROL =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 aria-[invalid=true]:border-destructive";

function groupTitle(name: string): string {
  const head = name.split(".")[0] ?? name;
  return GROUP_TITLES[head] ?? head.charAt(0).toUpperCase() + head.slice(1);
}

function show(value: unknown): string {
  return value === null || value === undefined ? "" : String(value);
}

function FieldErrors({ id, messages }: { id: string; messages: string[] | undefined }) {
  if (messages === undefined) return null;
  return (
    <>
      {messages.map((message) => (
        <p key={message} id={id} role="alert" className="text-sm text-destructive">
          {message}
        </p>
      ))}
    </>
  );
}

function Fixed() {
  return <p className="text-sm text-muted-foreground">Fixed by the deployment</p>;
}

/** Draft state and the save for one form: only the changed fields are sent. */
function useSettingsSave(path: string, convert: (name: string, value: unknown) => unknown) {
  const client = useKarniClient();
  const queryClient = useQueryClient();
  const { success } = useToast();
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [errors, setErrors] = useState<FormErrors>({ fields: {}, general: null });
  const [saved, setSaved] = useState(false);
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      client.request<unknown>(path, { method: "PATCH", body }),
    onSuccess: async () => {
      setErrors({ fields: {}, general: null });
      setSaved(true);
      success("Saved");
      await queryClient.invalidateQueries({ queryKey: PREFERENCES_KEY });
      setDraft({});
    },
    onError: (failure) => {
      setSaved(false);
      setErrors(readFormErrors(failure));
    },
  });
  function change(name: string, value: unknown, original: unknown): void {
    setSaved(false);
    setDraft((now) => {
      const same = typeof value === "boolean" ? value === original : show(value) === show(original);
      const rest = Object.fromEntries(Object.entries(now).filter(([key]) => key !== name));
      return same ? rest : { ...rest, [name]: value };
    });
  }
  function submit(): void {
    const body: Record<string, unknown> = {};
    for (const [name, value] of Object.entries(draft)) body[name] = convert(name, value);
    save.mutate(body);
  }
  return { draft, errors, saved, pending: save.isPending, change, submit };
}

function SaveRow({
  pending,
  saved,
  dirty,
  errors,
  onSave,
}: {
  pending: boolean;
  saved: boolean;
  dirty: boolean;
  errors: FormErrors;
  onSave: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <PendingButton pending={pending} pendingLabel="Saving…" disabled={!dirty} onClick={onSave}>
        Save
      </PendingButton>
      {saved ? (
        <p role="status" className="text-sm text-muted-foreground">
          Saved
        </p>
      ) : null}
      {errors.general !== null ? (
        <p role="alert" className="text-sm text-destructive">
          {errors.general}
        </p>
      ) : null}
    </div>
  );
}

/** The logo: shown, replaced by choosing a file (sent at once), or removed. */
function LogoField({
  id,
  label,
  url,
  readOnly,
}: {
  id: string;
  label: string;
  url: string;
  readOnly: boolean;
}) {
  const client = useKarniClient();
  const queryClient = useQueryClient();
  const { success, error } = useToast();
  const send = useMutation({
    mutationFn: (body: FormData | { logo: null }) =>
      client.request<unknown>("/preferences/details/", { method: "PATCH", body }),
    onSuccess: async () => {
      success("Saved");
      await queryClient.invalidateQueries({ queryKey: PREFERENCES_KEY });
    },
    onError: () => error("The logo was not changed", { description: "Try another file." }),
  });
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      {url !== "" ? (
        <img src={url} alt={label} className="h-16 w-auto max-w-full rounded border" />
      ) : (
        <p className="text-sm text-muted-foreground">No logo yet</p>
      )}
      {readOnly ? null : (
        <div className="flex flex-wrap items-center gap-3">
          <input
            id={id}
            type="file"
            accept="image/*"
            className="max-w-full text-sm"
            disabled={send.isPending}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file === undefined) return;
              const body = new FormData();
              body.append("logo", file);
              send.mutate(body);
            }}
          />
          {url !== "" ? (
            <Button
              type="button"
              variant="outline"
              disabled={send.isPending}
              onClick={() => send.mutate({ logo: null })}
            >
              Remove the logo
            </Button>
          ) : null}
        </div>
      )}
    </div>
  );
}

function DetailsForm({ details }: { details: Details }) {
  const prefix = useId();
  const form = useSettingsSave("/preferences/details/", (_name, value) => show(value));
  return (
    <form
      className="max-w-96 space-y-5"
      onSubmit={(event) => {
        event.preventDefault();
        form.submit();
      }}
    >
      {details.fields.map((field) => {
        const id = `${prefix}-${field.name}`;
        const locked = details.locked.includes(field.name);
        const readOnly = locked || !details.can_change;
        if (field.type === "file") {
          return (
            <LogoField
              key={field.name}
              id={id}
              label={field.label}
              url={show(details.values[field.name])}
              readOnly={readOnly}
            />
          );
        }
        const original = show(details.values[field.name]);
        const value = field.name in form.draft ? show(form.draft[field.name]) : original;
        const messages = form.errors.fields[field.name];
        const shared = {
          id,
          value,
          disabled: readOnly,
          "aria-invalid": messages !== undefined || undefined,
          "aria-describedby":
            field.help !== undefined && field.help !== "" ? `${id}-help` : undefined,
        };
        return (
          <div key={field.name} className="space-y-1">
            <Label htmlFor={id}>{field.label}</Label>
            {field.type === "textarea" ? (
              <Textarea
                {...shared}
                rows={4}
                onChange={(event) => form.change(field.name, event.target.value, original)}
              />
            ) : field.type === "choice" ? (
              <select
                {...shared}
                className={cn(CONTROL)}
                onChange={(event) => form.change(field.name, event.target.value, original)}
              >
                {(field.choices ?? []).map((choice) => (
                  <option key={choice.value} value={choice.value}>
                    {choice.label}
                  </option>
                ))}
              </select>
            ) : (
              <Input
                {...shared}
                type={field.type === "email" ? "email" : "text"}
                onChange={(event) => form.change(field.name, event.target.value, original)}
              />
            )}
            {field.help !== undefined && field.help !== "" ? (
              <p id={`${id}-help`} className="text-sm text-muted-foreground">
                {field.help}
              </p>
            ) : null}
            {locked ? <Fixed /> : null}
            <FieldErrors id={`${id}-error`} messages={messages} />
          </div>
        );
      })}
      {details.can_change ? (
        <SaveRow
          pending={form.pending}
          saved={form.saved}
          dirty={Object.keys(form.draft).length > 0}
          errors={form.errors}
          onSave={form.submit}
        />
      ) : null}
    </form>
  );
}

function SectionForm({ section }: { section: Section }) {
  const prefix = useId();
  const properties = section.schema.properties ?? {};
  const form = useSettingsSave(`/preferences/sections/${section.key}/`, (name, value) => {
    const kind = properties[name]?.type;
    if (kind === "integer" || kind === "number") {
      if (show(value).trim() === "") return section.defaults[name] ?? null;
      return Number(value);
    }
    return value;
  });
  return (
    <form
      className="max-w-96 space-y-5"
      onSubmit={(event) => {
        event.preventDefault();
        form.submit();
      }}
    >
      {section.describe !== "" ? (
        <p className="text-sm text-muted-foreground">{section.describe}</p>
      ) : null}
      {Object.entries(properties).map(([name, property]) => {
        const id = `${prefix}-${name}`;
        const label = property.title ?? name;
        const locked = section.locked.includes(name);
        const readOnly = locked || !section.can_change;
        const original = section.values[name];
        const current = name in form.draft ? form.draft[name] : original;
        const messages = form.errors.fields[name];
        const help = property.description;
        const describedBy = help !== undefined && help !== "" ? `${id}-help` : undefined;
        const invalid = messages !== undefined || undefined;
        let control: ReactNode;
        if (property.type === "boolean") {
          return (
            <div key={name} className="space-y-1">
              <div className="flex items-center gap-2">
                <input
                  id={id}
                  type="checkbox"
                  className="h-4 w-4 accent-primary"
                  checked={current === true}
                  disabled={readOnly}
                  aria-invalid={invalid}
                  aria-describedby={describedBy}
                  onChange={(event) => form.change(name, event.target.checked, original === true)}
                />
                <Label htmlFor={id}>{label}</Label>
              </div>
              {help !== undefined && help !== "" ? (
                <p id={`${id}-help`} className="text-sm text-muted-foreground">
                  {help}
                </p>
              ) : null}
              {locked ? <Fixed /> : null}
              <FieldErrors id={`${id}-error`} messages={messages} />
            </div>
          );
        }
        if (property.enum !== undefined) {
          control = (
            <select
              id={id}
              className={cn(CONTROL)}
              value={show(current)}
              disabled={readOnly}
              aria-invalid={invalid}
              aria-describedby={describedBy}
              onChange={(event) => form.change(name, event.target.value, original)}
            >
              {property.enum.map((choice) => (
                <option key={show(choice)} value={show(choice)}>
                  {show(choice)}
                </option>
              ))}
            </select>
          );
        } else if (property.type === "integer" || property.type === "number") {
          control = (
            <Input
              id={id}
              type="number"
              inputMode="decimal"
              step={property.type === "integer" ? 1 : "any"}
              min={property.minimum}
              max={property.maximum}
              value={show(current)}
              disabled={readOnly}
              aria-invalid={invalid}
              aria-describedby={describedBy}
              onChange={(event) => form.change(name, event.target.value, original)}
            />
          );
        } else {
          control = (
            <Input
              id={id}
              type="text"
              maxLength={property.maxLength}
              value={show(current)}
              disabled={readOnly}
              aria-invalid={invalid}
              aria-describedby={describedBy}
              onChange={(event) => form.change(name, event.target.value, original)}
            />
          );
        }
        return (
          <div key={name} className="space-y-1">
            <Label htmlFor={id}>{label}</Label>
            {control}
            {help !== undefined && help !== "" ? (
              <p id={`${id}-help`} className="text-sm text-muted-foreground">
                {help}
              </p>
            ) : null}
            {locked ? <Fixed /> : null}
            <FieldErrors id={`${id}-error`} messages={messages} />
          </div>
        );
      })}
      {section.can_change ? (
        <SaveRow
          pending={form.pending}
          saved={form.saved}
          dirty={Object.keys(form.draft).length > 0}
          errors={form.errors}
          onSave={form.submit}
        />
      ) : null}
    </form>
  );
}

function EmailRow({
  item,
  canChange,
  onEdit,
}: {
  item: EmailItem;
  canChange: boolean;
  onEdit: () => void;
}) {
  const client = useKarniClient();
  const queryClient = useQueryClient();
  const { error } = useToast();
  const id = useId();
  const toggle = useMutation({
    mutationFn: (on: boolean) =>
      client.request<unknown>(`/preferences/emails/${item.name}/`, {
        method: "PATCH",
        body: { on },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PREFERENCES_KEY }),
    onError: () => error("The switch was not changed", { description: "Try again." }),
  });
  const fixed = item.switchable === false;
  return (
    <li className="flex flex-wrap items-start justify-between gap-3 py-3">
      <div className="min-w-0 flex-1 space-y-1">
        <p id={`${id}-title`} className="font-medium">
          {item.title}
        </p>
        {item.describe !== "" ? (
          <p className="text-sm text-muted-foreground">{item.describe}</p>
        ) : null}
        {item.audience !== undefined && item.audience !== "" ? (
          <p className="text-sm text-muted-foreground">To: {item.audience}</p>
        ) : null}
      </div>
      <div className="flex items-center gap-3">
        {fixed ? (
          <span className="text-sm text-muted-foreground">Always sent</span>
        ) : (
          <input
            type="checkbox"
            role="switch"
            className="h-5 w-5 accent-primary"
            aria-labelledby={`${id}-title`}
            checked={item.on}
            disabled={!canChange || item.locked || toggle.isPending}
            onChange={(event) => toggle.mutate(event.target.checked)}
          />
        )}
        {item.locked && !fixed ? (
          <span className="text-sm text-muted-foreground">Fixed by the deployment</span>
        ) : null}
        {item.editable === true ? (
          <Button
            variant="outline"
            aria-label={`Edit ${item.title}`}
            disabled={!canChange}
            onClick={onEdit}
          >
            Edit
          </Button>
        ) : null}
      </div>
    </li>
  );
}

function EmailsPanel({ emails }: { emails: Preferences["emails"] }) {
  const [editing, setEditing] = useState<string | null>(null);
  if (editing !== null) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" onClick={() => setEditing(null)}>
          Back to the emails
        </Button>
        <EmailTemplateEditor kind={editing} />
      </div>
    );
  }
  const groups = new Map<string, EmailItem[]>();
  for (const item of emails.items) {
    const title = groupTitle(item.name);
    groups.set(title, [...(groups.get(title) ?? []), item]);
  }
  const from = emails.sender.from;
  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <p>
          Sent from:{" "}
          <span className="font-medium">{from !== "" ? from : "The project's default sender"}</span>
        </p>
        <p className="text-sm text-muted-foreground">The sender is set on the Details tab.</p>
      </div>
      {[...groups.entries()].map(([title, items]) => (
        <section key={title} aria-label={title} className="space-y-1">
          <h2 className="text-lg font-semibold">{title}</h2>
          <ul className="[&>*+*]:border-t [&>*+*]:border-border">
            {items.map((item) => (
              <EmailRow
                key={item.name}
                item={item}
                canChange={emails.can_change}
                onEdit={() => setEditing(item.name)}
              />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function ConnectionRow({ item, canChange }: { item: ConnectionItem; canChange: boolean }) {
  const client = useKarniClient();
  const queryClient = useQueryClient();
  const { error } = useToast();
  const id = useId();
  const toggle = useMutation({
    mutationFn: (on: boolean) =>
      client.request<unknown>(`/preferences/connections/${item.name}/`, {
        method: "PATCH",
        body: { on },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PREFERENCES_KEY }),
    onError: () => error("The switch was not changed", { description: "Try again." }),
  });
  return (
    <li className="flex flex-wrap items-start justify-between gap-3 py-3">
      <div className="min-w-0 flex-1 space-y-1">
        <p id={`${id}-title`} className="font-medium">
          {item.title}
        </p>
        {item.describe !== "" ? (
          <p className="text-sm text-muted-foreground">{item.describe}</p>
        ) : null}
        {!item.installed ? (
          <p className="text-sm text-muted-foreground">Needs {item.needs.join(", ")}</p>
        ) : null}
      </div>
      <div className="flex items-center gap-3">
        <input
          type="checkbox"
          role="switch"
          className="h-5 w-5 accent-primary"
          aria-labelledby={`${id}-title`}
          checked={item.on}
          disabled={!canChange || item.locked || toggle.isPending}
          onChange={(event) => toggle.mutate(event.target.checked)}
        />
        {item.locked ? (
          <span className="text-sm text-muted-foreground">Fixed by the deployment</span>
        ) : null}
      </div>
    </li>
  );
}

function ConnectionsPanel({ connections }: { connections: Preferences["connections"] }) {
  return (
    <div className="space-y-2">
      <p className="text-sm text-muted-foreground">
        What the parts of this project do together. Each one switches itself on when what it needs
        is installed.
      </p>
      <ul className="[&>*+*]:border-t [&>*+*]:border-border">
        {connections.items.map((item) => (
          <ConnectionRow key={item.name} item={item} canChange={connections.can_change} />
        ))}
      </ul>
    </div>
  );
}

export function SettingsPage({ title = "Settings", siteName }: SettingsPageProps) {
  const client = useKarniClient();
  usePageMeta({ title, siteName });
  const query = useQuery({
    queryKey: PREFERENCES_KEY,
    queryFn: () => client.request<Preferences>("/preferences/"),
    retry: false,
  });
  const [tab, setTab] = useState("details");
  let body: ReactNode;
  if (query.isPending) {
    body = <p role="status">Loading the settings…</p>;
  } else if (query.error instanceof KarniApiError && query.error.status === 403) {
    body = <EmptyState title="You may not change any setting." />;
  } else if (query.data === undefined) {
    body = <p role="alert">The settings could not be loaded.</p>;
  } else {
    const prefs = query.data;
    body = (
      <Tabs value={tab} onValueChange={setTab}>
        <div className="max-w-full overflow-x-auto">
          <TabsList aria-label="Settings">
            <TabsTrigger value="details">Details</TabsTrigger>
            {prefs.sections.map((section) => (
              <TabsTrigger key={section.key} value={`section-${section.key}`}>
                {section.title}
              </TabsTrigger>
            ))}
            <TabsTrigger value="emails">Emails</TabsTrigger>
            {prefs.connections.items.length > 0 ? (
              <TabsTrigger value="connections">Connections</TabsTrigger>
            ) : null}
          </TabsList>
        </div>
        <TabsContent value="details" className="pt-4">
          <DetailsForm details={prefs.details} />
        </TabsContent>
        {prefs.sections.map((section) => (
          <TabsContent key={section.key} value={`section-${section.key}`} className="pt-4">
            <SectionForm section={section} />
          </TabsContent>
        ))}
        <TabsContent value="emails" className="pt-4">
          <EmailsPanel emails={prefs.emails} />
        </TabsContent>
        {prefs.connections.items.length > 0 ? (
          <TabsContent value="connections" className="pt-4">
            <ConnectionsPanel connections={prefs.connections} />
          </TabsContent>
        ) : null}
      </Tabs>
    );
  }
  return (
    <div className="min-w-0 space-y-6">
      <h1 className="text-2xl font-semibold">{title}</h1>
      {body}
    </div>
  );
}
