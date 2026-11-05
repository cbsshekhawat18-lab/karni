import { TreeView } from "@karni/ui";

/** The intervention categories the user may open: granted nodes and their branches can be chosen. */
export default function CategoryTree({ value, onChange }: { value: string | null; onChange: (id: string | null) => void }) {
    return (
        <TreeView
            resource="interventions"
            access={{ permission: "intel.company:view" }}
            value={value}
            onChange={(next) => onChange(next === null ? null : String(next))}
            aria-label="Intervention categories"
        />
    );
}
