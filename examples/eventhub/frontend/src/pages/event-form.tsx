import { Page, ResourceForm, useUnsavedChangesGuard } from "@karni/ui";
import { useBlocker, useNavigate, useParams } from "@tanstack/react-router";

export default function EventFormPage() {
    const { id } = useParams({ strict: false });
    const navigate = useNavigate();
    // Leaving a dirty form in-app asks first; reloads are ResourceForm's own guard.
    const guard = useUnsavedChangesGuard({ beforeUnload: false });
    useBlocker({ shouldBlockFn: guard.shouldBlock, enableBeforeUnload: false });
    return (
        <Page title={id === undefined ? "New event" : "Edit event"}>
            <ResourceForm
                resource="events"
                id={id}
                onDirtyChange={guard.setDirty}
                onSuccess={(result) =>
                    void navigate({ to: "/events/$id", params: { id: String(result.id) } })
                }
            />
        </Page>
    );
}
