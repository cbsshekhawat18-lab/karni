/**
 * Experimental. The one Settings page of a project, built on
 * `GET /preferences/`: the details of the business, one tab for each
 * settings section a part declares, and the emails the project sends.
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
  type: "text" | "textarea" | "email" | "choice";
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
  audience: string;
  transactional: boolean;
  switchable: boolean;
  source: string;
  default: boolean;
  on: boolean;
  locked: boolean;
}

interface Preferences {
  contract: number;
  details: Details;
  sections: Section[];
  emails: {
    sender: { sender_name: string; sender_email: string; reply_to: string; from: string };
    items: EmailItem[];
    can_change: boolean;
  };
}

const PREFERENCES_KEY = ["karni", "preferences"];
const SOURCE_TITLES: Record<string, string> = {
  commerce: "Orders",
  shop: "Shop",
  accounts: "Accounts",
};
const CONTROL =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 aria-[invalid=true]:border-destructive";

function sourceTitle(source: string): string {
  const head = source.split(".")[0] ?? source;
  return SOURCE_TITLES[head] ?? head.charAt(0).toUpperCase() + head.slice(1);
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
  const fixed = !item.switchable;
  return (
    <li className="flex flex-wrap items-start justify-between gap-3 py-3">
      <div className="min-w-0 flex-1 space-y-1">
        <p id={`${id}-title`} className="font-medium">
          {item.title}
        </p>
        <p className="text-sm text-muted-foreground">{item.describe}</p>
        <p className="text-sm text-muted-foreground">To: {item.audience}</p>
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
        <Button
          variant="outline"
          aria-label={`Edit ${item.title}`}
          disabled={!canChange}
          onClick={onEdit}
        >
          Edit
        </Button>
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
    const title = sourceTitle(item.source);
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
