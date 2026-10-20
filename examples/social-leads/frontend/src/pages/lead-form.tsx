import { Page, ResourceForm } from "@karni/ui";
import { useNavigate, useParams } from "@tanstack/react-router";

export default function LeadFormPage() {
    const { id } = useParams({ strict: false });
    const navigate = useNavigate();
    return (
        <Page title={id === undefined ? "New lead" : "Edit lead"}>
            <ResourceForm
                resource="leads"
                id={id}
                onSuccess={(result) =>
                    void navigate({ to: "/leads/$id", params: { id: String(result.id) } })
                }
            />
        </Page>
    );
}
