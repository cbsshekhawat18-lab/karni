// Google Identity Services: the app's own call into the provider's SDK (@karni/ui bundles none).
// VITE_GOOGLE_CLIENT_ID is the same web client id the backend lists in
// KARNI_SOCIAL_GOOGLE_CLIENT_IDS.
interface Moment {
    isDismissedMoment(): boolean;
    isNotDisplayed(): boolean;
    isSkippedMoment(): boolean;
}
interface Gsi {
    accounts: {
        id: {
            initialize(options: { client_id: string; callback: (response: { credential: string }) => void }): void;
            prompt(listener: (moment: Moment) => void): void;
        };
    };
}
declare global {
    interface Window {
        google?: Gsi;
    }
}

function loadSdk(): Promise<Gsi> {
    return new Promise((resolve, reject) => {
        if (window.google) return resolve(window.google);
        const script = document.createElement("script");
        script.src = "https://accounts.google.com/gsi/client";
        script.onload = () => (window.google ? resolve(window.google) : reject(new Error("Google SDK missing")));
        script.onerror = () => reject(new Error("Google SDK did not load"));
        document.head.appendChild(script);
    });
}

/** Resolves with the ID token, or null when the user closed the prompt. */
export async function getGoogleIdToken(): Promise<string | null> {
    const google = await loadSdk();
    return new Promise((resolve) => {
        const client_id = (import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined) ?? "";
        google.accounts.id.initialize({ client_id, callback: (response) => resolve(response.credential) });
        google.accounts.id.prompt((moment) => {
            if (moment.isNotDisplayed() || moment.isSkippedMoment() || moment.isDismissedMoment()) resolve(null);
        });
    });
}
