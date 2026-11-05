// Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
import { Button, Page, ResourceDetail } from "@karni/ui";
import { useNavigate, useParams } from "@tanstack/react-router";

export default function PersonDetailPage() {
    const { id } = useParams({ from: "/persons/$id" });
    const navigate = useNavigate();
    return (
        <Page
            title="Person"
            actions={
                <Button onClick={() => void navigate({ to: "/persons/$id/edit", params: { id } })}>
                    Edit
                </Button>
            }
        >
            <ResourceDetail resource="persons" id={id} expand={["company"]} />
        </Page>
    );
}
