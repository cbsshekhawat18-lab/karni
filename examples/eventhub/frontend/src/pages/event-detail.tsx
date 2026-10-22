import { Button, Page, ResourceDetail, usePermission } from "@karni/ui";
import { useNavigate, useParams, useRouter } from "@tanstack/react-router";
import { TierList } from "../components/TierList";

export default function EventDetailPage() {
    const { id } = useParams({ from: "/events/$id" });
    const navigate = useNavigate();
    const router = useRouter();
    const { hasRole } = usePermission();
    const manage = hasRole("organizer") || hasRole("staff");
    return (
        <Page
            title="Event"
            actions={
                manage ? (
                    <>
                        <Button
                            variant="outline"
                            onClick={() =>
                                void navigate({ to: "/events/$id/dashboard", params: { id } })
                            }
                        >
                            Dashboard
                        </Button>
                        <Button
                            onClick={() => void navigate({ to: "/events/$id/edit", params: { id } })}
                        >
                            Edit
                        </Button>
                    </>
                ) : null
            }
        >
            <ResourceDetail
                resource="events"
                id={id}
                enableDelete={manage}
                onDeleted={() => void navigate({ to: "/events" })}
            />
            <h2 className="mt-6 text-lg font-semibold">Tickets</h2>
            <TierList
                event={id}
                onBook={(tier) => router.history.push(`/bookings/new?event=${id}&tier=${tier}`)}
            />
        </Page>
    );
}
