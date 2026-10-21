import { AuthProvider, KarniProvider, Toaster, createKarniClient } from "@karni/ui";
import { RouterProvider } from "@tanstack/react-router";
import { router } from "./routes";

const client = createKarniClient({ baseUrl: "/api" });

export default function App() {
    return (
        <KarniProvider client={client}>
            <AuthProvider>
                <RouterProvider router={router} />
                <Toaster />
            </AuthProvider>
        </KarniProvider>
    );
}
