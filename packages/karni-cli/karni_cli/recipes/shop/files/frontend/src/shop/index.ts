// What the shop adds to the app, once at startup: its account section, its panel on the
// staff's order page and its record links (./register). A project that composes several
// parts calls each part's register() from one place.
import { registerShop } from "./register";

export function register(): void {
  registerShop();
}
