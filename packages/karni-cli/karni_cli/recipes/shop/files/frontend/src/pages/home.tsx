// The home page: for staff the tiles of their role (karni.yaml's dashboard: and the code
// tiles of shop/dashboard.py and karni-commerce), for everyone else the shop's front page.
import { DashboardTiles, EmptyState, Page } from "@karni/ui";
import { useRouter } from "@tanstack/react-router";
import { StoreHome } from "../shop/Home";
import { usePerson } from "../shop/staff";

function StaffHome() {
  const router = useRouter();
  return (
    <Page title="Dashboard" description="What to send, what came in and what runs low.">
      <DashboardTiles
        onOpen={(href) => router.history.push(href)}
        empty={<EmptyState title="Nothing for your role here yet" />}
      />
    </Page>
  );
}

export default function HomePage() {
  const person = usePerson();
  if (person === "loading") return null;
  return person === "staff" ? <StaffHome /> : <StoreHome />;
}
