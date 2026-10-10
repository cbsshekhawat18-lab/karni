import { Button, Page, ResourceTable } from "@karni/ui";
import { useNavigate } from "@tanstack/react-router";

export default function BookingsPage() {
    const navigate = useNavigate();
    return (
        <Page
            title="Bookings"
            actions={
                <Button onClick={() => void navigate({ to: "/bookings/new" })}>New</Button>
            }
        >
            <ResourceTable
                resource="bookings"
                onRowClick={(row) =>
                    void navigate({ to: "/bookings/$id", params: { id: String(row.id) } })
                }
                onEdit={(row) =>
                    void navigate({ to: "/bookings/$id/edit", params: { id: String(row.id) } })
                }
            />
        </Page>
    );
}
