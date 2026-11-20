// What the shop adds to the app, once at startup: its storefront as the public home, its
// panel on the staff's order page and its coupon limit (./register).
// frontend/src/karni/parts.ts, which karni build writes, calls each part's register() in
// the order of app.recipes.
import { registerShop } from "./register";

export function register(): void {
  registerShop();
}
