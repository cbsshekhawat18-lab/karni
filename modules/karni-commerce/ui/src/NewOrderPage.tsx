/**
 * Experimental. An order staff place by hand, for a buyer who called: find
 * the items of any kind the project sells (a product, a booking, a course: a
 * kind filter shows when there are several), set how many, type who it is for
 * and where it goes, a coupon, the way to send it and, when every line allows
 * one, a deposit first. The server prices it (`orders/manual/quote/`, shown
 * before placing: the discount, the shipping, the tax and the total) and
 * holds the items as checkout does, and (unless unticked) emails the buyer
 * the link to pay. The order's page opens once it is placed.
 */
import {
  Button,
  Input,
  Label,
  Page,
  PendingButton,
  Textarea,
  useKarniClient,
  usePageMeta,
} from "@karni/ui";
import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { AddressFields, EMPTY_ADDRESS } from "./AddressFields";
import { problemOf } from "./cart";
import { ShippingChoice } from "./CheckoutPage";
import { Money } from "./Money";
import { PayChoice, payWayFor } from "./PayChoice";
import { useCommerce } from "./routes";
import { Totals } from "./Totals";
import type { Address, PayWay, Quote, SellableItem, SellableKind } from "./types";

interface Chosen extends SellableItem {
  quantity: number;
}

export interface NewOrderPageProps {
  title?: string;
  siteName?: string;
  /** Only items of this kind (default: every kind the project sells, with a filter). */
  kind?: string;
}

export function NewOrderPage({ title = "New order", siteName, kind }: NewOrderPageProps) {
  const client = useKarniClient();
  const { paths, navigate } = useCommerce();
  const [typed, setTyped] = useState("");
  const [search, setSearch] = useState("");
  const [chosen, setChosen] = useState<Chosen[]>([]);
  const [email, setEmail] = useState("");
  const [billing, setBilling] = useState<Address>(EMPTY_ADDRESS);
  const [note, setNote] = useState("");
  const [sendLink, setSendLink] = useState(true);
  const [coupon, setCoupon] = useState("");
  const [method, setMethod] = useState<string | null>(null);
  const [payWay, setPayWay] = useState<PayWay>("full");
  const [picked, setPicked] = useState("");
  usePageMeta({ title, siteName });
  const sold = useQuery<SellableKind[]>({
    queryKey: ["karni-commerce", "kinds"],
    enabled: kind === undefined,
    queryFn: ({ signal }) => client.request<SellableKind[]>("/orders/kinds/", { signal }),
  });
  const kindsSold = sold.data ?? [];
  const wanted = kind ?? picked;
  useEffect(() => {
    const wait = setTimeout(() => setSearch(typed.trim()), 300);
    return () => clearTimeout(wait);
  }, [typed]);
  const items = useQuery<SellableItem[]>({
    queryKey: ["karni-commerce", "items", wanted, search],
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) =>
      client.request<SellableItem[]>("/orders/items/", {
        query: { search, ...(wanted ? { kind: wanted } : {}) },
        signal,
      }),
  });
  const lines = chosen.map((line) => ({
    kind: line.kind,
    item: line.item,
    options: line.options,
    quantity: line.quantity,
  }));
  const quote = useQuery<Quote>({
    queryKey: [
      "karni-commerce",
      "manual-quote",
      JSON.stringify(lines),
      billing.country,
      billing.region,
      billing.postcode,
      coupon.trim(),
      method ?? "",
      email,
    ],
    enabled: chosen.length > 0,
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) =>
      client.request<Quote>("/orders/manual/quote/", {
        method: "POST",
        body: {
          email: email.includes("@") ? email : "",
          billing: {
            country: billing.country,
            region: billing.region ?? "",
            postcode: billing.postcode,
          },
          coupon: coupon.trim(),
          shipping_method: method ?? "",
          lines,
        },
        signal,
      }),
  });
  const place = useMutation({
    mutationFn: () =>
      client.request<{ id: string; number: number; link: string }>("/orders/manual/", {
        method: "POST",
        body: {
          email,
          name: billing.name,
          billing,
          note,
          send_link: sendLink,
          coupon: coupon.trim(),
          shipping_method: method ?? quote.data?.method ?? "",
          pay: payWayFor(quote.data, payWay),
          lines,
        },
      }),
    onSuccess: (placed) => navigate(paths.order(placed.number)),
  });
  const add = (item: SellableItem) => {
    const same = (line: Chosen) =>
      line.kind === item.kind &&
      line.item === item.item &&
      JSON.stringify(line.options) === JSON.stringify(item.options);
    const known = chosen.find(same);
    setChosen(
      known
        ? chosen.map((line) => (line === known ? { ...line, quantity: line.quantity + 1 } : line))
        : [...chosen, { ...item, quantity: 1 }],
    );
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    place.mutate();
  };
  return (
    <Page
      title={title}
      description="An order for a customer who called. They pay by the link we email them."
    >
      <form onSubmit={submit} className="grid gap-6 lg:grid-cols-2">
        <section aria-label="Items" className="space-y-3">
          <h2 className="font-semibold">Items</h2>
          {kindsSold.length > 1 ? (
            <div className="space-y-1">
              <Label htmlFor="item-kind">Kind</Label>
              <select
                id="item-kind"
                className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={picked}
                onChange={(event) => setPicked(event.target.value)}
              >
                <option value="">Every kind</option>
                {kindsSold.map((row) => (
                  <option key={row.kind} value={row.kind}>
                    {row.label}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
          <Label htmlFor="item-search">Find an item</Label>
          <Input
            id="item-search"
            type="search"
            placeholder="Name or SKU"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
          />
          <ul
            aria-label="Found items"
            className="max-h-72 divide-y divide-border overflow-y-auto rounded-lg border border-border"
          >
            {(items.data ?? []).map((item) => (
              <li
                key={`${item.kind}:${item.item}:${JSON.stringify(item.options)}`}
                className="flex items-center justify-between gap-2 p-2 text-sm"
              >
                <span className="min-w-0">
                  {item.name}
                  <span className="block text-xs text-muted-foreground">
                    {[
                      kindsSold.length > 1 ? (item.kind_label ?? item.kind) : "",
                      item.sku,
                      item.available !== null ? `${item.available} available` : "",
                    ]
                      .filter(Boolean)
                      .join(", ")}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  <Money value={item.price} />
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={item.available !== null && item.available <= 0}
                    onClick={() => add(item)}
                    aria-label={`Add ${item.name}`}
                  >
                    Add
                  </Button>
                </span>
              </li>
            ))}
            {items.data?.length === 0 ? (
              <li className="p-3 text-sm text-muted-foreground">Nothing matches.</li>
            ) : null}
          </ul>
          <h3 className="pt-2 font-semibold">On the order</h3>
          {chosen.length === 0 ? (
            <p className="text-sm text-muted-foreground">Add the items the customer wants.</p>
          ) : (
            <ul aria-label="On the order" className="space-y-2">
              {chosen.map((line) => (
                <li
                  key={`${line.kind}:${line.item}:${JSON.stringify(line.options)}`}
                  className="flex items-center gap-2 text-sm"
                >
                  <Label htmlFor={`qty-${line.item}`} className="min-w-0 flex-1">
                    {line.name}
                  </Label>
                  <Input
                    id={`qty-${line.item}`}
                    type="number"
                    min={1}
                    className="w-20"
                    value={line.quantity}
                    onChange={(event) =>
                      setChosen(
                        chosen.map((other) =>
                          other === line
                            ? { ...other, quantity: Math.max(1, Number(event.target.value) || 1) }
                            : other,
                        ),
                      )
                    }
                  />
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => setChosen(chosen.filter((other) => other !== line))}
                    aria-label={`Take ${line.name} off`}
                  >
                    Remove
                  </Button>
                </li>
              ))}
            </ul>
          )}
          {chosen.length > 0 && quote.data ? (
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
          ) : null}
          {quote.isError ? (
            <p role="alert" className="text-sm text-destructive">
              {problemOf(quote.error)}
            </p>
          ) : null}
        </section>
        <section aria-label="Customer" className="space-y-3">
          <h2 className="font-semibold">Customer</h2>
          <div className="space-y-1">
            <Label htmlFor="order-email">Email</Label>
            <Input
              id="order-email"
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </div>
          <AddressFields legend="Address" value={billing} onChange={setBilling} section="billing" />
          <ShippingChoice
            quote={quote.data}
            chosen={method}
            onChoose={setMethod}
            waiting={quote.isFetching}
          />
          <PayChoice quote={quote.data} chosen={payWay} onChoose={setPayWay} payer="the customer" />
          <div className="space-y-1">
            <Label htmlFor="order-coupon">Coupon (optional)</Label>
            <Input
              id="order-coupon"
              value={coupon}
              autoComplete="off"
              aria-describedby="order-coupon-problem"
              onChange={(event) => setCoupon(event.target.value)}
            />
            {quote.data?.coupon_problem ? (
              <p id="order-coupon-problem" role="alert" className="text-sm text-destructive">
                {quote.data.coupon_problem}
              </p>
            ) : null}
          </div>
          <div className="space-y-1">
            <Label htmlFor="order-note">Note on the order</Label>
            <Textarea
              id="order-note"
              rows={2}
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={sendLink}
              onChange={(event) => setSendLink(event.target.checked)}
            />
            Email the customer the link to pay
          </label>
          {place.isError ? (
            <p role="alert" className="text-sm text-destructive">
              {problemOf(place.error)}
            </p>
          ) : null}
          <PendingButton type="submit" pending={place.isPending} disabled={chosen.length === 0}>
            Place the order
          </PendingButton>
        </section>
      </form>
    </Page>
  );
}
