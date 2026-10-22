import { Button, Page, ResourceTable, usePermission, useResourceMutations } from "@karni/ui";
import { useNavigate } from "@tanstack/react-router";

export default function EventsPage() {
    const navigate = useNavigate();
    const { hasRole } = usePermission();
    const organizer = hasRole("organizer") || hasRole("staff");
    const { remove } = useResourceMutations("events");
    const deleteAll = (ids: string[]) =>
        Promise.all(ids.map((id) => remove.mutateAsync(id))).then(() => undefined);
    return (
        <Page
            title="Events"
            description="Browse and search what's on; organizers see their drafts too."
            actions={
                organizer ? (
                    <Button onClick={() => void navigate({ to: "/events/new" })}>New event</Button>
                ) : null
            }
        >
            <ResourceTable
                resource="events"
                columns={[
                    { field: "title" },
                    { field: "starts_at" },
                    { field: "venue" },
                    { field: "status" },
                ]}
                expand={["venue"]}
                initialSorting={[{ id: "starts_at", desc: false }]}
                onRowClick={(row) =>
                    void navigate({ to: "/events/$id", params: { id: String(row.id) } })
                }
                onEdit={
                    organizer
                        ? (row) =>
                              void navigate({
                                  to: "/events/$id/edit",
                                  params: { id: String(row.id) },
                              })
                        : undefined
                }
                enableDelete={organizer}
                bulkActions={
                    organizer ? [{ label: "Delete", destructive: true, onClick: deleteAll }] : undefined
                }
            />
        </Page>
    );
}
