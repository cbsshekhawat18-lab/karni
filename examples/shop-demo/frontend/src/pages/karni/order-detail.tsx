// Written by karni build from karni.yaml. Do not edit it: karni build rewrites it.
import { Page, ResourceDetail } from "@karni/ui";
import { useParams } from "@tanstack/react-router";

export default function OrderDetailPage() {
    const { id } = useParams({ from: "/orders/$id" });
    return (
        <Page title="Order">
            <ResourceDetail resource="orders" id={id} expand={["payment"]} />
        </Page>
    );
}
