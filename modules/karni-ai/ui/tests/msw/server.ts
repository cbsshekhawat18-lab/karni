import { setupServer } from "msw/node";
import { handlers } from "./handlers";

export const server = setupServer(...handlers);

export { API_BASE, extractFixture, handlers, jobFixture, resetMswData, state } from "./handlers";
