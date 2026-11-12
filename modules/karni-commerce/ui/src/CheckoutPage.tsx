/**
 * Checkout: who orders (signed in, or a guest with an email), the billing
 * address, a shipping address when a line is sent somewhere, a note, then the
 * payment at the provider. The server works out the totals and holds the
 * items: nothing here is a price the server trusts.
 */
import {
  Button,
  Checkbox,
  EmptyState,
  Input,
  KarniApiError,
  Label,
  PendingButton,
  Skeleton,
  TermsGate,
  Textarea,
  useAuth,
  useKarniClient,
  usePageMeta,
} from "@karni/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type ReactNode } from "react";
import { AddressFields, EMPTY_ADDRESS } from "./AddressFields";
import { CART_QUERY_KEY, cartHeaders, problemOf, useCart } from "./cart";
import { Money } from "./Money";
import { CommerceLink, useCommerce } from "./routes";
import type { Address, Placed } from "./types";

export interface CheckoutPageProps {
  title?: string;
  siteName?: string;
  /**
   * A way to pick a saved address (an address book), shown above the billing
   * address for a signed-in person: call `pick` with the address chosen.
   */
  addressPicker?: (pick: (address: Address) => void) => ReactNode;
  /** Ask a signed-in person to accept the current terms before paying (default true). */
  terms?: boolean;
}

function fieldErrors(error: unknown, part: string): Record<string, string> {
  if (!(error instanceof KarniApiError) || !error.data || typeof error.data !== "object") return {};
  const found = (error.data as Record<string, unknown>)[part];
  if (!found || typeof found !== "object") return {};
  return Object.fromEntries(
    Object.entries(found as Record<string, unknown>).map(([key, value]) => [
      key,
      Array.isArray(value) ? String(value[0]) : String(value),
    ]),
  );
}

export function CheckoutPage({
  title = "Checkout",
  siteName,
  addressPicker,
  terms = true,
}: CheckoutPageProps) {
  const client = useKarniClient();
  const queries = useQueryClient();
  const { paths, navigate } = useCommerce();
  const { status, user } = useAuth();
  const cart = useCart();
  const signedIn = status === "authenticated";
  const [email, setEmail] = useState("");
  const [billing, setBilling] = useState<Address>(EMPTY_ADDRESS);
  const [elsewhere, setElsewhere] = useState(false);
  const [shipping, setShipping] = useState<Address>(EMPTY_ADDRESS);
  const [note, setNote] = useState("");
  const ids = { email: useId(), note: useId(), elsewhere: useId() };
  usePageMeta({ title, siteName });
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
        },
      }),
    onSuccess: (placed) => {
      void queries.invalidateQueries({ queryKey: CART_QUERY_KEY });
      if (placed.url) window.location.assign(placed.url);
      else navigate(paths.order(placed.number, placed.key));
    },
  });
  if (cart.isPending || status === "loading") return <Skeleton className="h-96 w-full" />;
  if (!cart.data || cart.data.lines.length === 0) {
    return (
      <EmptyState
        title="Nothing to check out"
        description="Your cart is empty."
        action={<Button onClick={() => navigate(paths.browse)}>Start shopping</Button>}
      />
    );
  }
  const shipped = cart.data.needs_shipping;
  const place = (
    <div className="space-y-3">
      {order.isError ? (
        <p role="alert" className="text-sm font-medium text-destructive">
          {problemOf(order.error)}
        </p>
      ) : null}
      <PendingButton
        pending={order.isPending}
        disabled={!cart.data.ready}
        className="w-full"
        onClick={() => order.mutate()}
      >
        Place the order and pay
      </PendingButton>
      <p className="text-sm text-muted-foreground">
        By placing the order you accept the{" "}
        <CommerceLink to={paths.terms} className="underline">
          terms
        </CommerceLink>
        .
      </p>
    </div>
  );
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{title}</h1>
      <div className="grid gap-8 lg:grid-cols-3">
        <div className="space-y-8 lg:col-span-2">
          <section className="space-y-3" aria-labelledby={ids.email}>
            <h2 id={ids.email} className="text-lg font-semibold">
              Contact
            </h2>
            {signedIn ? (
              <p>
                Signed in as <strong>{user?.email}</strong>. The confirmation goes there.
              </p>
            ) : (
              <div className="flex flex-col gap-1 sm:w-96">
                <Label htmlFor={`${ids.email}-input`}>Email, for the confirmation</Label>
                <Input
                  id={`${ids.email}-input`}
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                />
                <p className="text-sm text-muted-foreground">
                  Or{" "}
                  <CommerceLink to={paths.signIn(paths.checkout)} className="underline">
                    sign in
                  </CommerceLink>{" "}
                  to find your orders in your account later.
                </p>
              </div>
            )}
          </section>
          {signedIn && addressPicker ? addressPicker(setBilling) : null}
          <AddressFields
            legend="Billing address"
            section="billing"
            value={billing}
            onChange={setBilling}
            errors={fieldErrors(order.error, "billing")}
          />
          {shipped ? (
            <div className="flex items-center gap-2">
              <Checkbox
                id={ids.elsewhere}
                checked={elsewhere}
                onCheckedChange={(on) => setElsewhere(on === true)}
              />
              <Label htmlFor={ids.elsewhere}>Send it to a different address</Label>
            </div>
          ) : null}
          {shipped && elsewhere ? (
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
        </div>
        <aside
          className="h-fit space-y-4 rounded-lg border border-border bg-card p-4"
          aria-label="Your order"
        >
          <h2 className="text-lg font-semibold">Your order</h2>
          <ul className="space-y-2 text-sm">
            {cart.data.lines.map((line) => (
              <li key={line.id} className="flex justify-between gap-2">
                <span>
                  {line.quantity} x {line.name}
                  {line.problem ? (
                    <span className="block text-destructive">{line.problem}</span>
                  ) : null}
                </span>
                <Money value={line.line_total} />
              </li>
            ))}
          </ul>
          <p className="flex justify-between border-t border-border pt-3 font-semibold">
            Total <Money value={cart.data.subtotal} />
          </p>
          {signedIn && terms ? <TermsGate page={false}>{place}</TermsGate> : place}
        </aside>
      </div>
    </div>
  );
}
