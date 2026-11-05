import { ChartCard, ComparisonTable, DashboardCard, DashboardGrid, DataTable } from "@karni/ui";
import { Page, useResourceList } from "@karni/ui";

type Venue = { id: string; name: string; city: string; capacity: number };
type City = { city: string; venues: number; seats: number };

const columns = [
    { key: "city", header: "City" },
    { key: "venues", header: "Venues" },
    { key: "seats", header: "Seats" },
];
const metrics = [
    { key: "city", label: "City" },
    { key: "capacity", label: "Seats", better: "higher" as const },
];

/** Seats by venue and by city: rows the page computes from one list request. */
export default function VenueOverviewPage() {
    const venues = useResourceList<Venue>("venues", { pageSize: 100, ordering: "-capacity" });
    const rows = venues.data?.results ?? [];
    const top = rows.slice(0, 3);
    const byCity = new Map<string, City>();
    for (const { city, capacity } of rows) {
        const seen = byCity.get(city) ?? { city, venues: 0, seats: 0 };
        byCity.set(city, { city, venues: seen.venues + 1, seats: seen.seats + capacity });
    }
    const state = { loading: venues.isPending, error: venues.error, onRetry: venues.refetch };
    return (
        <Page title="Venues" description="Seats by venue and by city.">
            <DashboardGrid>
                <ChartCard
                    title="Seats per venue"
                    kind="bar"
                    span={2}
                    {...state}
                    data={rows.map((venue) => ({ label: venue.name, value: venue.capacity }))}
                />
                <DashboardCard title="Largest venues" {...state} empty={rows.length === 0}>
                    <ComparisonTable caption="Largest venues" entities={top} metrics={metrics} />
                </DashboardCard>
                <DashboardCard title="Cities" span="full" {...state} empty={rows.length === 0}>
                    <DataTable caption="Cities" columns={columns} rows={[...byCity.values()]} />
                </DashboardCard>
            </DashboardGrid>
        </Page>
    );
}
