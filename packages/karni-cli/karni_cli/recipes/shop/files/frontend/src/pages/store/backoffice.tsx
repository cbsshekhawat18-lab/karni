// /backoffice: the staff dashboard. Each model that declares class Karni: dashboard shows its
// counts and newest rows (shop/models.py), opened in the back office's own pages.
import { Dashboard, Page } from "@karni/ui";
import { useRouter } from "@tanstack/react-router";

export default function BackofficePage() {
  const router = useRouter();
  const open = (path: string, exists: string): void => {
    if (exists in router.routesByPath) router.history.push(path);
  };
  return (
    <Page
      title="Dashboard"
      description="Orders to fulfil, and what came in last."
    >
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
