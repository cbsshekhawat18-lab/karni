// The customer's account: their orders, their saved addresses and their name.
import {
  Button,
  EmptyState,
  ErrorState,
  Input,
  Label,
  PendingButton,
  ResourceForm,
  ResourceTable,
  Skeleton,
  useAuth,
  useKarniClient,
  useResourceList,
  useToast,
  usePageMeta,
} from "@karni/ui";
import { useMutation } from "@tanstack/react-query";
import { Link, useRouter } from "@tanstack/react-router";
import { useId, useState } from "react";
import { STATUS_WORDS } from "./OrderView";
import { Money } from "./Price";
import { SHOP_NAME } from "./StoreLayout";
import type { OrderRow } from "./types";

function Orders() {
  const orders = useResourceList<OrderRow>("orders", {
    pageSize: 50,
    ordering: "-created_at",
  });
  if (orders.isPending) return <Skeleton className="h-40 w-full" />;
  if (orders.isError)
    return (
      <ErrorState error={orders.error} onRetry={() => void orders.refetch()} />
    );
  const rows = orders.data.results;
  if (rows.length === 0) {
    return (
      <EmptyState
        title="No orders yet"
        headingLevel={3}
        action={<Link to="/shop">Browse the shop</Link>}
      />
    );
  }
  return (
    <ul className="divide-y divide-border rounded-lg border border-border">
      {rows.map((row) => (
        <li key={row.id}>
          <Link
            to="/order/$number"
            params={{ number: String(row.number) }}
            className="flex flex-wrap items-center justify-between gap-2 p-3 hover:bg-muted"
          >
            <span className="font-medium">Order {row.number}</span>
            <span className="text-sm text-muted-foreground">
              {new Date(row.created_at).toLocaleDateString()}
            </span>
            <span className="text-sm">
              {STATUS_WORDS[row.status] ?? row.status}
            </span>
            <Money value={row.total} className="font-medium" />
          </Link>
        </li>
      ))}
    </ul>
  );
}

function Profile() {
  const client = useKarniClient();
  const { user, refresh } = useAuth();
  const { success } = useToast();
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
      success("Saved");
    },
  });
  return (
    <div className="flex flex-wrap items-end gap-3">
      <p className="w-full text-sm text-muted-foreground">
        Email: {user?.email}
      </p>
      <div className="flex flex-col gap-1">
        <Label htmlFor={ids.first}>First name</Label>
        <Input
          id={ids.first}
          value={first}
          onChange={(event) => setFirst(event.target.value)}
        />
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor={ids.last}>Last name</Label>
        <Input
          id={ids.last}
          value={last}
          onChange={(event) => setLast(event.target.value)}
        />
      </div>
      <PendingButton pending={save.isPending} onClick={() => save.mutate()}>
        Save
      </PendingButton>
    </div>
  );
}

export function AccountView() {
  usePageMeta({ title: "Your account", siteName: SHOP_NAME });
  return (
    <div className="space-y-10">
      <section aria-labelledby="orders" className="space-y-3">
        <h1 id="orders" className="text-2xl font-semibold">
          Your orders
        </h1>
        <Orders />
      </section>
      <section aria-labelledby="addresses" className="space-y-3">
        <h2 id="addresses" className="text-xl font-semibold">
          Saved addresses
        </h2>
        <Link to="/account/addresses" className="underline">
          Add and change your addresses
        </Link>
      </section>
      <section aria-labelledby="profile" className="space-y-3">
        <h2 id="profile" className="text-xl font-semibold">
          Your details
        </h2>
        <Profile />
      </section>
    </div>
  );
}

export function AddressBook() {
  const router = useRouter();
  const [editing, setEditing] = useState<string | null | undefined>(undefined);
  usePageMeta({ title: "Your addresses", siteName: SHOP_NAME });
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Your addresses</h1>
      {editing === undefined ? (
        <>
          <Button onClick={() => setEditing(null)}>Add an address</Button>
          <ResourceTable
            resource="addresses"
            onEdit={(row) => setEditing(String(row.id))}
          />
        </>
      ) : (
        <ResourceForm
          resource="addresses"
          id={editing ?? undefined}
          onSuccess={() => setEditing(undefined)}
          actions={
            <Button variant="ghost" onClick={() => setEditing(undefined)}>
              Cancel
            </Button>
          }
        />
      )}
      <Button variant="ghost" onClick={() => router.history.push("/account")}>
        Back to your account
      </Button>
    </div>
  );
}
