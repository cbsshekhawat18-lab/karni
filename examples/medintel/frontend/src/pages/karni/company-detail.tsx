// Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
import { Button, Page, ResourceDetail } from "@karni/ui";
import { useNavigate, useParams } from "@tanstack/react-router";

export default function CompanyDetailPage() {
    const { id } = useParams({ from: "/companies/$id" });
    const navigate = useNavigate();
    return (
        <Page
            title="Company"
            actions={
                <Button onClick={() => void navigate({ to: "/companies/$id/edit", params: { id } })}>
                    Edit
                </Button>
            }
        >
            <ResourceDetail
                resource="companies"
                id={id}
                related={["trials", "brands"]}
            />
        </Page>
    );
}
