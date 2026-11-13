// /settings: the shop's settings, without code (@karni/ui): the business's details and
// email sender, checkout, the shop's stock and catalogue options, and every email (its
// switch and its text, which a manager rewrites with the merge fields shown).
import { SettingsPage } from "@karni/ui";
import { useShopName } from "../shop/StoreLayout";

export default function Settings() {
  return <SettingsPage siteName={useShopName()} />;
}
