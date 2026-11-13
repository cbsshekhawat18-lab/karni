// /account: the person's details and the sections the shop registers (@karni/ui).
import { AccountPage as Account } from "@karni/ui";
import { useShopName } from "../shop/StoreLayout";

export default function AccountPage() {
  const shopName = useShopName();
  return <Account siteName={shopName} />;
}
