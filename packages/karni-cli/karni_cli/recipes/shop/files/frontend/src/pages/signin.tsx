// /signin: a code by email (which opens an account too) or a password, then back to
// where the person was going (?next=).
import { SignInPage as SignIn } from "@karni/ui";
import { useRouter } from "@tanstack/react-router";
import { useSearchValues } from "../shop/search";
import { SHOP_NAME } from "../shop/StoreLayout";

export default function SignInPage() {
  const router = useRouter();
  const next = useSearchValues().next;
  return (
    <SignIn
      siteName={SHOP_NAME}
      next={next}
      fallback="/"
      navigate={(to) => router.history.push(to)}
    />
  );
}
