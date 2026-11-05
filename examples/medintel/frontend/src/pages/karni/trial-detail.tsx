// Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
import { Button, Page, ResourceDetail } from "@karni/ui";
import { useNavigate, useParams } from "@tanstack/react-router";

export default function TrialDetailPage() {
    const { id } = useParams({ from: "/trials/$id" });
    const navigate = useNavigate();
    return (
        <Page
            title="Trial"
            actions={
                <Button onClick={() => void navigate({ to: "/trials/$id/edit", params: { id } })}>
                    Edit
                </Button>
            }
        >
            <ResourceDetail
                resource="trials"
                id={id}
                expand={["sponsor", "investigator"]}
            />
        </Page>
    );
}
