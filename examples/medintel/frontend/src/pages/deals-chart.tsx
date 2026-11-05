import { DashboardCard, DashboardGrid, Page } from "@karni/ui";
import { SavedChart } from "@karni/charts-ui";
import { useState } from "react";
import CategoryTree from "../components/CategoryTree";

/** Two charts the admin defines (Charts), narrowed to one intervention category. */
export default function DealsChartPage() {
    const [category, setCategory] = useState<string | null>(null);
    const filters = category ? { interventions: category, interventions_descendants: true } : {};
    return (
        <Page title="Deals" description="Charts saved in the admin, read under your grants.">
            <DashboardGrid columns={3}>
                <DashboardCard title="Categories">
                    <CategoryTree value={category} onChange={setCategory} />
                </DashboardCard>
                <DashboardGrid columns={2} className="xl:col-span-2">
                    <SavedChart chart="deal-value-by-year" filters={filters} />
                    <SavedChart chart="deals-by-year" filters={filters} />
                </DashboardGrid>
            </DashboardGrid>
        </Page>
    );
}
