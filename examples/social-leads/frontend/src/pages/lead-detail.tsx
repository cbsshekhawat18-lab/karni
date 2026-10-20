import { Button, Page, ResourceDetail, useResourceItem } from "@karni/ui";
import { useNavigate, useParams } from "@tanstack/react-router";
import { useState } from "react";
import { assigneeLabel } from "../components/assignee";
import { LeadActions } from "../components/LeadActions";
import { LeadTimeline } from "../components/LeadTimeline";

export default function LeadDetailPage() {
    const { id } = useParams({ from: "/leads/$id" });
    const navigate = useNavigate();
    const [version, setVersion] = useState(0);
    const lead = useResourceItem<{ status: string; name: string; phone: string }>("leads", id);
    const refresh = () => {
        setVersion((v) => v + 1);
        void lead.refetch();
    };
    const actions = (
        <>
            <LeadActions id={id} status={lead.data?.status ?? "new"} onChange={refresh} />
            <Button variant="outline" onClick={() => void navigate({ to: "/leads/$id/edit", params: { id } })}>
                Edit
            </Button>
        </>
    );
    return (
        <Page title={lead.data?.name || lead.data?.phone || "Lead"} actions={actions}>
            <ResourceDetail
                key={version}
                resource="leads"
                id={id}
                expand={["workspace", "contact", "assigned_to"]}
                fields={{ assigned_to: { label: "Assigned to", render: assigneeLabel } }}
                sections={[<LeadTimeline key={`timeline-${version}`} leadId={id} />]}
            />
        </Page>
    );
}
