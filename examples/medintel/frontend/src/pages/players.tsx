import { ChartCard, DashboardCard, DashboardGrid, DataTable, Page } from "@karni/ui";
import { useState } from "react";
import { useCompaniesList, useDealsAggregate } from "../api/hooks";
import CategoryTree from "../components/CategoryTree";

const columns = [
    { key: "name", header: "Company" },
    { key: "country", header: "Country" },
    { key: "website", header: "Website" },
];

/** Companies in an intervention category (and below it), and the deal value they bought. */
export default function PlayersPage() {
    const [category, setCategory] = useState<string | null>(null);
    const filters = category ? { interventions: category, interventions_descendants: true } : {};
    const companies = useCompaniesList({ pageSize: 100, filters });
    const deals = useDealsAggregate({ groupBy: "acquirer__name", metric: "sum", value: "value", top: 5, filters });
    return (
        <Page title="Players" description="Pick a category to see who works in it.">
            <DashboardGrid columns={3}>
                <DashboardCard title="Categories">
                    <CategoryTree value={category} onChange={setCategory} />
                </DashboardCard>
                <ChartCard title="Deal value by buyer" kind="bar" span={2} aggregate={deals.data} loading={deals.isPending} error={deals.error} />
                <DashboardCard title="Companies" span="full" loading={companies.isPending} error={companies.error} empty={companies.data?.results.length === 0}>
                    <DataTable caption="Companies" columns={columns} rows={companies.data?.results ?? []} />
                </DashboardCard>
            </DashboardGrid>
        </Page>
    );
}
