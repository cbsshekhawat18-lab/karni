// Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
import { Button, Page, ResourceDetail } from "@karni/ui";
import { useNavigate, useParams } from "@tanstack/react-router";

export default function ProductDetailPage() {
    const { id } = useParams({ from: "/products/$id" });
    const navigate = useNavigate();
    return (
        <Page
            title="Product"
            actions={
                <Button onClick={() => void navigate({ to: "/products/$id/edit", params: { id } })}>
                    Edit
                </Button>
            }
        >
            <ResourceDetail resource="products" id={id} expand={["category"]} />
        </Page>
    );
}
