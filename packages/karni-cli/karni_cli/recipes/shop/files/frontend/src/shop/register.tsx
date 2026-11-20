// What the shop adds to the family pages, once at startup: its storefront as the public
// home (what / shows to visitors and customers, the "Storefront" button of the back office
// goes to /shop), where an empty cart sends the buyer and where the terms are, the parcel
// panel on the staff's order page, and categories as a coupon limit. The cart, checkout,
// orders, the "Your orders" section of /account and the Orders tab of a person's page are
// karni-commerce's (frontend/src/karni/parts.ts registers them).
import {
  registerCommercePaths,
  registerCouponLimit,
  registerOrderPanel,
} from "@karni/commerce-ui";
import { registerPublicHome } from "@karni/ui";
import { StoreHome } from "./Home";
import { ParcelPanel } from "./ParcelPanel";

export function registerShop(): void {
  registerPublicHome({ key: "shop", component: StoreHome, path: "/shop", order: 10 });
  registerCommercePaths({ browse: "/shop/catalogue", terms: "/shop/terms" });
  registerOrderPanel({
    key: "parcel",
    title: "Parcel",
    order: 10,
    component: ParcelPanel,
    kinds: ["product"],
    when: (order) => order.needs_shipping,
  });
  registerCouponLimit({
    key: "categories",
    label: "Categories",
    resource: "categories",
    labelField: "name",
  });
}
