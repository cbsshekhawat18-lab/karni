// The shop's terms. Replace the text with your own, and move features.terms.version in
// karni.yaml forward when it changes: customers then accept the new version at checkout.
import { usePageMeta } from "@karni/ui";
import { SHOP_NAME } from "./StoreLayout";

export function Terms() {
  usePageMeta({
    title: "Terms",
    siteName: SHOP_NAME,
    description: `The terms of sale of ${SHOP_NAME}.`,
  });
  return (
    <article className="space-y-4">
      <h1 className="text-2xl font-semibold">Terms of sale</h1>
      <p>These terms are an example. Write your own before the shop opens.</p>
      <h2 className="text-lg font-semibold">Orders</h2>
      <p>
        An order is accepted once its payment is confirmed. We email the
        confirmation to the address given at checkout.
      </p>
      <h2 className="text-lg font-semibold">Prices</h2>
      <p>
        Prices are shown in the shop&apos;s currency. The price you pay is the
        one in your cart at checkout.
      </p>
      <h2 className="text-lg font-semibold">Returns</h2>
      <p>
        Write here how many days a customer has to return an item, and how
        refunds are paid.
      </p>
    </article>
  );
}
