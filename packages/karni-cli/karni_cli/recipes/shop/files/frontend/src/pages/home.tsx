// The home page: the staff's dashboard (orders, parcels and stock, each a tile the models
// declare), and for everyone else the shop's front page.
import { Dashboard, Page } from "@karni/ui";
import { useRouter } from "@tanstack/react-router";
import { StoreHome } from "../shop/Home";
import { usePerson } from "../shop/staff";

function StaffHome() {
  const router = useRouter();
  const open = (path: string, exists: string): void => {
    if (exists in router.routesByPath) router.history.push(path);
  };
  return (
    <Page title="Dashboard" description="Orders, parcels to send and stock.">
      <Dashboard
        onOpen={(resource, row) =>
          open(`/${resource}/${String(row.id)}`, `/${resource}/$id`)
        }
        onOpenList={(resource, filters) => {
          const query = new URLSearchParams();
          for (const [name, value] of Object.entries(filters)) {
            if (value != null) query.set(`${resource}.${name}`, String(value));
          }
          open(
            `/${resource}${query.size > 0 ? `?${query.toString()}` : ""}`,
            `/${resource}`,
          );
        }}
      />
    </Page>
  );
}

export default function HomePage() {
  const person = usePerson();
  if (person === "loading") return null;
  return person === "staff" ? <StaffHome /> : <StoreHome />;
}
