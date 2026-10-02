/**
 * Dev health probe. src/api/ is the one home of raw HTTP
 * (karni/no-direct-http allows it); everywhere else, data access goes through
 * the typed hooks and client that `karni types` generates into this
 * directory.
 */
export type Health = "ok" | "fail" | "unreachable";

export async function fetchHealth(): Promise<Health> {
    try {
        const response = await fetch("/health/ready/");
        const data: unknown = await response.json();
        const status =
            typeof data === "object" && data !== null
                ? (data as { status?: unknown }).status
                : undefined;
        return status === "ok" ? "ok" : "fail";
    } catch {
        return "unreachable";
    }
}
