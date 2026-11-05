// Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
import { Page, ResourceForm } from "@karni/ui";
import { useNavigate, useParams } from "@tanstack/react-router";

export default function ConditionFormPage() {
    const { id } = useParams({ strict: false });
    const navigate = useNavigate();
    return (
        <Page title={id === undefined ? "New condition" : "Edit condition"}>
            <ResourceForm
                resource="conditions"
                id={id}
                onSuccess={() => void navigate({ to: "/conditions" })}
            />
        </Page>
    );
}
