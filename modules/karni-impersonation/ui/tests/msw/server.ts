import { setupServer } from "msw/node";
import { handlers } from "./handlers";

export const server = setupServer(...handlers);

export { API_BASE, handlers, resetMswData, sessionFixture, state } from "./handlers";
