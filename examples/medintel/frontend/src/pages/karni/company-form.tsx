// Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
import { Page, ResourceForm } from "@karni/ui";
import { useNavigate, useParams } from "@tanstack/react-router";

export default function CompanyFormPage() {
    const { id } = useParams({ strict: false });
    const navigate = useNavigate();
    return (
        <Page title={id === undefined ? "New company" : "Edit company"}>
            <ResourceForm
                resource="companies"
                id={id}
                onSuccess={(result) =>
                    void navigate({ to: "/companies/$id", params: { id: String(result.id) } })
                }
            />
        </Page>
    );
}
