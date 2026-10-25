// The dashboard: a Stat per count and the newest rows of every model that
// opts in with `class Karni: dashboard = {...}` (events/models.py: Event and
// Booking). Nothing here names a model: the API's schema says what to show.
import { Dashboard, Page } from "@karni/ui";
import { useRouter } from "@tanstack/react-router";

export default function HomePage() {
    const router = useRouter();
    const open = (path: string, exists: string): void => {
        if (exists in router.routesByPath) router.history.push(path);
    };
    return (
        <Page title="Dashboard" description="What needs attention, and what came in last.">
            <Dashboard
                onOpen={(resource, row) =>
                    open(`/${resource}/${String(row.id)}`, `/${resource}/$id`)
                }
                onOpenList={(resource, filters) => {
                    const query = new URLSearchParams();
                    for (const [name, value] of Object.entries(filters)) {
                        if (value != null) query.set(`${resource}.${name}`, String(value));
                    }
                    const search = query.size > 0 ? `?${query.toString()}` : "";
                    open(`/${resource}${search}`, `/${resource}`);
                }}
            />
        </Page>
    );
}
