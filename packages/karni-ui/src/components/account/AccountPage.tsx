/**
 * Experimental. `/account`: the signed-in person's own page. Their details
 * (name, email) first, then the sections the installed parts registered
 * (`registerAccountSection`): orders, bookings, courses. With nothing
 * registered it is still a working profile page.
 */
import { useMutation } from "@tanstack/react-query";
import { useId, useState, type ReactNode } from "react";
import { useAuth } from "../../auth/provider";
import { usePageMeta } from "../../hooks/usePageMeta";
import { Button } from "../primitives/button";
import { Input } from "../primitives/input";
import { Label } from "../primitives/label";
import { PendingButton } from "../../states/PendingButton";
import { useKarniClient } from "../../schema/provider";
import { useToast } from "../toast/use-toast";
import { accountSections, type AccountSection } from "./sections";

export interface AccountPageProps {
  /** The page's heading and title. */
  title?: string;
  /** The site's name, after the title in the browser tab. */
  siteName?: string;
  /** The sections to show instead of the registered ones. */
  sections?: AccountSection[];
  /** Show the details section (default true). */
  details?: boolean;
  /** More content after the sections. */
  children?: ReactNode;
}

function Details() {
  const client = useKarniClient();
  const { user, refresh } = useAuth();
  const { success, error } = useToast();
  const [first, setFirst] = useState(String(user?.first_name ?? ""));
  const [last, setLast] = useState(String(user?.last_name ?? ""));
  const ids = { first: useId(), last: useId() };
  const save = useMutation({
    mutationFn: () =>
      client.request("/auth/me/", {
        method: "PATCH",
        body: { first_name: first, last_name: last },
      }),
    onSuccess: () => {
      void refresh();
      success("Your details are saved");
    },
    onError: () => error("Your details were not saved", { description: "Try again." }),
  });
  return (
    <div className="flex flex-wrap items-end gap-3">
      <p className="w-full text-sm text-muted-foreground">Email: {String(user?.email ?? "")}</p>
      <div className="flex flex-col gap-1">
        <Label htmlFor={ids.first}>First name</Label>
        <Input id={ids.first} value={first} onChange={(event) => setFirst(event.target.value)} />
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor={ids.last}>Last name</Label>
        <Input id={ids.last} value={last} onChange={(event) => setLast(event.target.value)} />
      </div>
      <PendingButton pending={save.isPending} onClick={() => save.mutate()}>
        Save
      </PendingButton>
    </div>
  );
}

export function AccountPage({
  title = "Your account",
  siteName,
  sections,
  details = true,
  children,
}: AccountPageProps) {
  const { roles, logout } = useAuth();
  usePageMeta({ title, siteName });
  const shown = (sections ?? accountSections()).filter(
    (section) => !section.roles || section.roles.some((role) => roles.includes(role)),
  );
  return (
    <div className="space-y-10">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-2xl font-semibold">{title}</h1>
        <Button variant="ghost" onClick={() => void logout()}>
          Sign out
        </Button>
      </header>
      {shown.map(({ key, title: heading, component: Section }) => (
        <section key={key} aria-labelledby={`account-${key}`} className="space-y-3">
          <h2 id={`account-${key}`} className="text-xl font-semibold">
            {heading}
          </h2>
          <Section />
        </section>
      ))}
      {details ? (
        <section aria-labelledby="account-details" className="space-y-3">
          <h2 id="account-details" className="text-xl font-semibold">
            Your details
          </h2>
          <Details />
        </section>
      ) : null}
      {children}
    </div>
  );
}
