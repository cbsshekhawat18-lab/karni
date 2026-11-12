// Checkout: who orders (signed in, or a guest with an email), where it goes, a note, then the
// payment at the provider. The server works out the totals and holds the stock.
import {
  Button,
  Checkbox,
  EmptyState,
  Input,
  KarniApiError,
  Label,
  PendingButton,
  Select,
  Skeleton,
  TermsGate,
  Textarea,
  useAuth,
  useKarniClient,
  useResourceList,
  usePageMeta,
} from "@karni/ui";
import { useMutation } from "@tanstack/react-query";
import { Link, useRouter } from "@tanstack/react-router";
import { useId, useState } from "react";
import { AddressFields, EMPTY_ADDRESS } from "./AddressFields";
import { cartHeaders, problemOf, useCart, useCartPlaced } from "./cart";
import { Money } from "./Price";
import { SHOP_NAME } from "./StoreLayout";
import type { Address } from "./types";

interface Placed {
  number: number;
  key: string;
  url: string;
}

interface SavedAddress extends Address {
  id: string;
  is_default: boolean;
}

function fieldErrors(error: unknown, part: string): Record<string, string> {
  if (
    !(error instanceof KarniApiError) ||
    !error.data ||
    typeof error.data !== "object"
  )
    return {};
  const found = (error.data as Record<string, unknown>)[part];
  if (!found || typeof found !== "object") return {};
  return Object.fromEntries(
    Object.entries(found as Record<string, unknown>).map(([key, value]) => [
      key,
      Array.isArray(value) ? String(value[0]) : String(value),
    ]),
  );
}

function SavedAddresses({ onPick }: { onPick: (address: Address) => void }) {
  const saved =
    useResourceList<SavedAddress>("addresses", { pageSize: 20 }).data
      ?.results ?? [];
  const id = useId();
  if (saved.length === 0) return null;
  return (
    <div className="flex flex-col gap-1 sm:w-80">
      <Label id={id}>Use a saved address</Label>
      <Select
        aria-labelledby={id}
        value={null}
        placeholder="Choose one"
        options={saved.map((row) => ({
          value: row.id,
          label: `${row.name}, ${row.line1}, ${row.city}`,
        }))}
        onValueChange={(value) => {
          const row = saved.find((item) => item.id === value);
          if (row) onPick(row);
        }}
      />
    </div>
  );
}

export function Checkout() {
  const client = useKarniClient();
  const router = useRouter();
  const { status, user } = useAuth();
  const cart = useCart();
  const placed = useCartPlaced();
  const signedIn = status === "authenticated";
  const [email, setEmail] = useState("");
  const [billing, setBilling] = useState<Address>(EMPTY_ADDRESS);
  const [elsewhere, setElsewhere] = useState(false);
  const [shipping, setShipping] = useState<Address>(EMPTY_ADDRESS);
  const [note, setNote] = useState("");
  const [save, setSave] = useState(true);
  const ids = {
    email: useId(),
    note: useId(),
    elsewhere: useId(),
    save: useId(),
  };
  usePageMeta({ title: "Checkout", siteName: SHOP_NAME });
  const order = useMutation({
    mutationFn: () =>
      client.request<Placed>("/carts/current/checkout/", {
        method: "POST",
        headers: cartHeaders(),
        body: {
          email: signedIn ? "" : email,
          billing,
          shipping: elsewhere ? shipping : null,
          note,
          save_address: signedIn && save,
        },
      }),
    onSuccess: (result) => {
      placed();
      window.location.assign(result.url);
    },
  });
  if (cart.isPending || status === "loading")
    return <Skeleton className="h-96 w-full" />;
  if (!cart.data || cart.data.lines.length === 0) {
    return (
      <EmptyState
        title="Nothing to check out"
        description="Your cart is empty."
        action={
          <Button onClick={() => router.history.push("/shop")}>
            Browse the shop
          </Button>
        }
      />
    );
  }
  const place = (
    <div className="space-y-3">
      {order.isError ? (
        <p role="alert" className="text-sm font-medium text-destructive">
          {problemOf(order.error)}
        </p>
      ) : null}
      <PendingButton
        pending={order.isPending}
        className="w-full"
        onClick={() => order.mutate()}
      >
        Place the order and pay
      </PendingButton>
      <p className="text-sm text-muted-foreground">
        By placing the order you accept the{" "}
        <Link to="/terms" className="underline">
          terms
        </Link>
        .
      </p>
    </div>
  );
  return (
    <div className="grid gap-8 lg:grid-cols-3">
      <div className="space-y-8 lg:col-span-2">
        <section className="space-y-3" aria-labelledby={ids.email}>
          <h2 className="text-lg font-semibold">Contact</h2>
          {signedIn ? (
            <p>
              Signed in as <strong>{user?.email}</strong>. The confirmation goes
              there.
            </p>
          ) : (
            <div className="flex flex-col gap-1 sm:w-96">
              <Label htmlFor={ids.email}>Email, for the confirmation</Label>
              <Input
                id={ids.email}
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
              <p className="text-sm text-muted-foreground">
                Or{" "}
                <Link
                  to="/signin"
                  search={{ next: "/checkout" }}
                  className="underline"
                >
                  sign in
                </Link>{" "}
                to see your orders and saved addresses later.
              </p>
            </div>
          )}
        </section>
        {signedIn ? <SavedAddresses onPick={setBilling} /> : null}
        <AddressFields
          legend="Billing address"
          section="billing"
          value={billing}
          onChange={setBilling}
          errors={fieldErrors(order.error, "billing")}
        />
        <div className="flex items-center gap-2">
          <Checkbox
            id={ids.elsewhere}
            checked={elsewhere}
            onCheckedChange={(on) => setElsewhere(on === true)}
          />
          <Label htmlFor={ids.elsewhere}>Ship to a different address</Label>
        </div>
        {elsewhere ? (
          <AddressFields
            legend="Shipping address"
            section="shipping"
            value={shipping}
            onChange={setShipping}
            errors={fieldErrors(order.error, "shipping")}
          />
        ) : null}
        <div className="flex flex-col gap-1">
          <Label htmlFor={ids.note}>A note for the order (optional)</Label>
          <Textarea
            id={ids.note}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        </div>
        {signedIn ? (
          <div className="flex items-center gap-2">
            <Checkbox
              id={ids.save}
              checked={save}
              onCheckedChange={(on) => setSave(on === true)}
            />
            <Label htmlFor={ids.save}>Save the address for next time</Label>
          </div>
        ) : null}
      </div>
      <aside
        className="space-y-4 rounded-lg border border-border bg-card p-4"
        aria-label="Your order"
      >
        <h2 className="text-lg font-semibold">Your order</h2>
        <ul className="space-y-2 text-sm">
          {cart.data.lines.map((line) => (
            <li key={line.id} className="flex justify-between gap-2">
              <span>
                {line.quantity} x {line.product.name}
              </span>
              <Money value={line.line_total} />
            </li>
          ))}
        </ul>
        <p className="flex justify-between border-t border-border pt-3 font-semibold">
          Total <Money value={cart.data.subtotal} />
        </p>
        {signedIn ? <TermsGate page={false}>{place}</TermsGate> : place}
      </aside>
    </div>
  );
}
