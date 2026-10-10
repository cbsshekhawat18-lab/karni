import { Page, ResourceForm } from "@karni/ui";
import { useNavigate, useParams } from "@tanstack/react-router";

export default function EventFormPage() {
    const { id } = useParams({ strict: false });
    const navigate = useNavigate();
    return (
        <Page title={id === undefined ? "New event" : "Edit event"}>
            <ResourceForm
                resource="events"
                id={id}
                onSuccess={(result) =>
                    void navigate({ to: "/events/$id", params: { id: String(result.id) } })
                }
            />
        </Page>
    );
}
