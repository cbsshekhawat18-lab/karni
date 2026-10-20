// Foreign keys to the user model carry no x-karni-relation (users are not an
// API resource), so ResourceDetail/ResourceTable print an expanded user as
// "[object Object]". FRICTION.md #11; this renders the email instead.
export function assigneeLabel(value: unknown): string {
    if (typeof value === "object" && value !== null && "email" in value) {
        return String((value as { email: unknown }).email);
    }
    return "—";
}
