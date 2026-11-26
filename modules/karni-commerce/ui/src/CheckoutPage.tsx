/**
 * Checkout: who orders (signed in, or a guest with an email), the billing
 * address, a shipping address when a line is sent somewhere, how to pay when
 * the order allows a deposit (`PayChoice`), a note, then the payment at the
 * provider. A free order is placed with no payment and opens its page. The
 * server works out the totals and holds the items: nothing here is a price the
 * server trusts.
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
import { CART_QUERY_KEY, cartHeaders, problemOf, useCart, useQuote } from "./cart";
import { CouponBox } from "./CouponBox";
import { Money } from "./Money";
import { PayChoice, payWayFor } from "./PayChoice";
import { CommerceLink, useCommerce } from "./routes";
import { LineDescription } from "./lines";
import { Totals } from "./Totals";
import type { Address, PayWay, Placed, Quote } from "./types";

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
  /** The country the address starts with (an ISO code: the shop's own country). */
  defaultCountry?: string;
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

function fieldMessage(error: unknown, field: string): string {
  if (!(error instanceof KarniApiError) || !error.data || typeof error.data !== "object") return "";
  const found = (error.data as Record<string, unknown>)[field];
  if (Array.isArray(found) && typeof found[0] === "string") return found[0];
  return typeof found === "string" ? found : "";
}

const METHOD_HINT: Record<string, string> = {
  pickup: "Collect it from us",
  free: "No charge",
};

/** The ways to send the order to the address, as radio buttons, with what each costs. */
/** The ways to send an order to its address, from a quote, to choose one. */
export function ShippingChoice({
  quote,
  chosen,
  onChoose,
  waiting,
}: {
  quote: Quote | undefined;
  chosen: string | null;
  onChoose: (id: string) => void;
  waiting: boolean;
}) {
  const name = useId();
  if (!quote || !quote.needs_shipping) return null;
  return (
    <fieldset className="space-y-2" aria-busy={waiting || undefined}>
      <legend className="text-lg font-semibold">Shipping</legend>
      {quote.shipping_problem ? (
        <p role="alert" className="text-sm font-medium text-destructive">
          {quote.shipping_problem}
        </p>
      ) : quote.methods.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          The ways to send it show once you enter the country.
        </p>
      ) : (
        <ul className="space-y-2">
          {quote.methods.map((method) => {
            const id = `${name}-${method.id}`;
            const selected = (chosen ?? quote.method) === method.id;
            return (
              <li key={method.id}>
                <label
                  htmlFor={id}
                  className="flex cursor-pointer items-center gap-3 rounded-md border border-border p-3 has-[:checked]:border-primary"
                >
                  <input
                    id={id}
                    type="radio"
                    name={name}
                    value={method.id}
                    checked={selected}
                    onChange={() => onChoose(method.id)}
                    className="h-4 w-4 accent-primary"
                  />
                  <span className="flex-1">
                    {method.name}
                    {METHOD_HINT[method.kind] ? (
                      <span className="block text-sm text-muted-foreground">
                        {METHOD_HINT[method.kind]}
                      </span>
                    ) : null}
                  </span>
                  <span className="tabular-nums">
                    {Number(method.cost) === 0 ? (
                      "Free"
                    ) : (
                      <Money value={method.cost} currency={quote.currency} />
                    )}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
    </fieldset>
  );
}

export function CheckoutPage({
  title = "Checkout",
  siteName,
  addressPicker,
  terms = true,
  defaultCountry = "",
}: CheckoutPageProps) {
  const client = useKarniClient();
  const queries = useQueryClient();
  const { paths, navigate } = useCommerce();
  const { status, user } = useAuth();
  const cart = useCart();
  const signedIn = status === "authenticated";
  const [email, setEmail] = useState("");
  const [billing, setBilling] = useState<Address>({
    ...EMPTY_ADDRESS,
    country: defaultCountry.toUpperCase(),
  });
  const [elsewhere, setElsewhere] = useState(false);
  const [shipping, setShipping] = useState<Address>(EMPTY_ADDRESS);
  const [note, setNote] = useState("");
  const [method, setMethod] = useState<string | null>(null);
  const [payWay, setPayWay] = useState<PayWay>("full");
  const [accepted, setAccepted] = useState(false);
  const ids = { email: useId(), note: useId(), elsewhere: useId(), terms: useId() };
  const needsTerms = cart.data?.checkout?.accept_terms === true;
  const destination = elsewhere ? shipping : billing;
  const quote = useQuote(
    { country: destination.country, region: destination.region, postcode: destination.postcode },
    method,
    signedIn ? "" : email,
  );
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
          shipping_method: method ?? quote.data?.method ?? "",
          pay: payWayFor(quote.data, payWay),
          ...(needsTerms ? { accept_terms: accepted } : {}),
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
  const options = cart.data.checkout;
  const mustSignIn = options?.guest_checkout === false && !signedIn;
  const termsError = fieldMessage(order.error, "accept_terms");
  const free = quote.data !== undefined && Number(quote.data.total) === 0;
  const placeLabel = free
    ? "Place the order"
    : payWayFor(quote.data, payWay) === "deposit"
      ? "Place the order and pay the deposit"
      : "Place the order and pay";
  const place = mustSignIn ? (
    <p>
      <CommerceLink to={paths.signIn(paths.checkout)} className="font-medium underline">
        Sign in to place an order
      </CommerceLink>
    </p>
  ) : (
    <div className="space-y-3">
      {needsTerms ? (
        <div className="space-y-1">
          <div className="flex items-start gap-2">
            <Checkbox
              id={ids.terms}
              required
              checked={accepted}
              onCheckedChange={(on) => setAccepted(on === true)}
            />
            <Label htmlFor={ids.terms}>
              I accept the{" "}
              <a
                href={options.terms_url || paths.terms}
                className="underline"
                target="_blank"
                rel="noreferrer"
              >
                terms of sale
              </a>
            </Label>
          </div>
          {termsError ? (
            <p role="alert" className="text-sm font-medium text-destructive">
              {termsError}
            </p>
          ) : null}
        </div>
      ) : null}
      {order.isError && !termsError ? (
        <p role="alert" className="text-sm font-medium text-destructive">
          {problemOf(order.error)}
        </p>
      ) : null}
      <PendingButton
        pending={order.isPending}
        disabled={!cart.data.ready || Boolean(quote.data?.shipping_problem)}
        className="w-full"
        onClick={() => order.mutate()}
      >
        {placeLabel}
      </PendingButton>
      {needsTerms ? null : (
        <p className="text-sm text-muted-foreground">
          By placing the order you accept the{" "}
          <CommerceLink to={paths.terms} className="underline">
            terms
          </CommerceLink>
          .
        </p>
      )}
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
          <ShippingChoice
            quote={quote.data}
            chosen={method}
            onChoose={setMethod}
            waiting={quote.isFetching}
          />
          <PayChoice quote={quote.data} chosen={payWay} onChoose={setPayWay} />
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
                {/* The quantity beside the line, so a kind's own renderer may take lines. */}
                <span className="flex min-w-0 gap-1">
                  <span className="shrink-0">{line.quantity} x</span>
                  <span className="min-w-0">
                    <LineDescription line={line} place="checkout" />
                    {line.problem ? (
                      <span className="block text-destructive">{line.problem}</span>
                    ) : null}
                  </span>
                </span>
                <Money value={line.line_total} />
              </li>
            ))}
          </ul>
          <CouponBox cart={cart.data} />
          {quote.data ? (
            <Totals
              className="border-t border-border pt-3 text-sm"
              currency={quote.data.currency}
              subtotal={quote.data.subtotal}
              discount={quote.data.discount}
              coupon={quote.data.coupon}
              shipping={
                !quote.data.needs_shipping
                  ? undefined
                  : quote.data.method === null
                    ? null
                    : quote.data.shipping
              }
              shippingMethod={
                quote.data.methods.find((option) => option.id === quote.data.method)?.name
              }
              taxLines={quote.data.tax_lines}
              pricesIncludeTax={quote.data.prices_include_tax}
              total={quote.data.total}
            />
          ) : (
            <p className="flex justify-between border-t border-border pt-3 font-semibold">
              Items <Money value={cart.data.subtotal} />
            </p>
          )}
          {signedIn && terms ? <TermsGate page={false}>{place}</TermsGate> : place}
        </aside>
      </div>
    </div>
  );
}
