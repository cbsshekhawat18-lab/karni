// /account: the person's details and the sections the shop registers (@karni/ui).
import { AccountPage as Account } from "@karni/ui";
import { SHOP_NAME } from "../shop/StoreLayout";

export default function AccountPage() {
  return <Account siteName={SHOP_NAME} />;
}
