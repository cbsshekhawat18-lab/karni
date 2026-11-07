import { ChartCard, DashboardGrid, Page } from "@karni/ui";
import { useTrialsAggregate } from "../api/hooks";

/** Trials by phase, status and start year, under the signed-in user's grants. */
export default function InsightsPage() {
    const phase = useTrialsAggregate({ groupBy: "phase" });
    const status = useTrialsAggregate({ groupBy: "status" });
    const year = useTrialsAggregate({ groupBy: "start_year", stack: "phase" });
    const enrolled = useTrialsAggregate({ groupBy: "start_year", metric: "sum", value: "enrollment" });
    return (
        <Page title="Trials" description="What is running, and how it changes by year.">
            <DashboardGrid>
                <ChartCard title="By phase" kind="bar" aggregate={phase.data} loading={phase.isPending} error={phase.error} />
                <ChartCard title="By status" kind="bar" aggregate={status.data} loading={status.isPending} error={status.error} />
                <ChartCard title="Started per year, by phase" kind="bar" span="full" aggregate={year.data} loading={year.isPending} error={year.error} />
                <ChartCard title="Enrollment per year" kind="line" span="full" aggregate={enrolled.data} loading={enrolled.isPending} error={enrolled.error} />
            </DashboardGrid>
        </Page>
    );
}
