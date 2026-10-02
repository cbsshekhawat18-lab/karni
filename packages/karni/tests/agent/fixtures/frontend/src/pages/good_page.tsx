import { Page, ResourceTable } from "@karni/ui";

// Known-good page for `karni rules --check`: composes @karni/ui, zero findings.
// The string "fetch(" in a comment or <table> in text is not code.
export function InvoicesPage() {
  const note = "do not call fetch( here";
  return (
    <Page title="Invoices">
      {/* a <table> mention inside a JSX comment */}
      <ResourceTable resource="invoices" />
      <p>{note}</p>
    </Page>
  );
}
