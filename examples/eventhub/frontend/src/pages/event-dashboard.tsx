import { Page, ResourceTable, Stat, buttonVariants, useKarniClient } from "@karni/ui";
import { useParams } from "@tanstack/react-router";
import { useEffect, useState } from "react";

interface Dashboard {
    bookings: number;
    tickets: number;
    capacity: number;
    revenue: string;
}

export default function EventDashboardPage() {
    const { id } = useParams({ from: "/events/$id/dashboard" });
    const client = useKarniClient();
    const [stats, setStats] = useState<Dashboard | null>(null);

    useEffect(() => {
        void client.request<Dashboard>(`/events/${id}/dashboard/`).then(setStats);
    }, [client, id]);

    return (
        <Page
            title="Dashboard"
            description="Confirmed bookings for this event, and who is coming."
            actions={
                <a className={buttonVariants()} href={`/api/events/${id}/attendees/`}>
                    Export attendees (CSV)
                </a>
            }
        >
            <div className="grid gap-4 sm:grid-cols-3">
                <Stat label="Confirmed bookings" value={stats?.bookings ?? "…"} />
                <Stat label="Tickets sold" value={stats ? `${stats.tickets} / ${stats.capacity}` : "…"} />
                <Stat label="Revenue" value={stats ? stats.revenue : "…"} />
            </div>
            <h2 className="mt-6 text-lg font-semibold">Bookings</h2>
            <ResourceTable resource="bookings" params={{ event: id }} filters={["status"]} />
        </Page>
    );
}
