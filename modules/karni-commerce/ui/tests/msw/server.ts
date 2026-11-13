/**
 * Shared MSW server; vitest.setup.ts wires listen/resetHandlers/close, so
 * suites only `server.use(...)` for per-test overrides.
 */
import { setupServer } from "msw/node";
import { handlers } from "./handlers";

export const server = setupServer(...handlers);

export { API_BASE, cartState, checkoutCalls, handlers, resetMswData } from "./handlers";
