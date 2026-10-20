import { Button, Modal, Page, ResourceImport, ResourceTable, Tabs, TabsContent, TabsList, TabsTrigger } from "@karni/ui";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { assigneeLabel } from "../components/assignee";
import { LeadKanban } from "../components/LeadKanban";
import { HIDDEN_COLUMNS } from "../components/lead-status";
import { useBulkStatus } from "../components/use-bulk-status";

export default function LeadsPage() {
    const navigate = useNavigate();
    const [version, setVersion] = useState(0);
    const refresh = () => setVersion((v) => v + 1);
    const bulkActions = useBulkStatus(refresh);
    const actions = (
        <>
            <Modal title="Import leads" trigger={<Button variant="outline">Import</Button>}>
                <ResourceImport resource="leads" onDone={refresh} />
            </Modal>
            <Button onClick={() => void navigate({ to: "/leads/new" })}>New</Button>
        </>
    );
    return (
        <Page title="Leads" description="Every lead captured from your flows." actions={actions}>
            <Tabs defaultValue="table">
                <TabsList>
                    <TabsTrigger value="table">Table</TabsTrigger>
                    <TabsTrigger value="board">Board</TabsTrigger>
                </TabsList>
                <TabsContent value="table">
                    <ResourceTable
                        key={version}
                        resource="leads"
                        bulkActions={bulkActions}
                        expand={["workspace", "contact", "assigned_to"]}
                        columns={[{ field: "assigned_to", header: "Assigned", cell: (row) => assigneeLabel(row.assigned_to) }, { field: "created_at" }]}
                        columnsOverride={(all) => all.filter((column) => !HIDDEN_COLUMNS.includes(String(column.id)))}
                        onRowClick={(row) => void navigate({ to: "/leads/$id", params: { id: String(row.id) } })}
                        onEdit={(row) => void navigate({ to: "/leads/$id/edit", params: { id: String(row.id) } })}
                    />
                </TabsContent>
                <TabsContent value="board">
                    <LeadKanban key={version} />
                </TabsContent>
            </Tabs>
        </Page>
    );
}
