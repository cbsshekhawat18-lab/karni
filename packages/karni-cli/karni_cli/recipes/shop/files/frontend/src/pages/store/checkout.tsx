// /checkout: contact, addresses and payment (store/Checkout.tsx).
import { Checkout } from "../../store/Checkout";

export default function CheckoutPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Checkout</h1>
      <Checkout />
    </div>
  );
}
