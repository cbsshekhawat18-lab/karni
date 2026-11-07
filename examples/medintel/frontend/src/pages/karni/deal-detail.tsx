// Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
import { Button, Page, ResourceDetail } from "@karni/ui";
import { useNavigate, useParams } from "@tanstack/react-router";

export default function DealDetailPage() {
    const { id } = useParams({ from: "/deals/$id" });
    const navigate = useNavigate();
    return (
        <Page
            title="Deal"
            actions={
                <Button onClick={() => void navigate({ to: "/deals/$id/edit", params: { id } })}>
                    Edit
                </Button>
            }
        >
            <ResourceDetail
                resource="deals"
                id={id}
                expand={["acquirer", "seller", "brand"]}
            />
        </Page>
    );
}
