// What the shop adds to the app, once at startup: its account section, its panel on the
// staff's order page and its record links (./register). frontend/src/karni/parts.ts,
// which karni build writes, calls each part's register() in the order of app.recipes.
import { registerShop } from "./register";

export function register(): void {
  registerShop();
}
