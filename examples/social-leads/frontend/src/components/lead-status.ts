// The pipeline stages, in board order (the model's Lead.Status, minus spam on the board).
export const STATUSES = [
    { value: "new", label: "New" },
    { value: "contacted", label: "Contacted" },
    { value: "qualified", label: "Qualified" },
    { value: "converted", label: "Converted" },
    { value: "lost", label: "Lost" },
    { value: "spam", label: "Spam" },
] as const;

export const BOARD = STATUSES.filter((status) => status.value !== "spam");

// Fields the original table did not show (ResourceTable shows every field;
// there is no "only these columns" prop, FRICTION.md #12).
export const HIDDEN_COLUMNS = [
    "workspace", "contact", "email", "interest", "budget", "location", "custom_fields", "source_channel",
    "source_ad_id", "source_campaign_id", "source_campaign_name", "source_adset_id", "quality_reason",
    "tags", "notes", "converted_at", "conversion_value", "capi_pushed_at",
];

export interface LeadRow {
    id: string;
    name: string;
    phone: string;
    interest: string;
    status: string;
    quality_score: number;
    source_ad_name: string;
}
