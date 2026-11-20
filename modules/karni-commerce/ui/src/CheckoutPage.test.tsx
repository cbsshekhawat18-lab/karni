import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { cartState, checkoutCalls } from "../tests/msw/handlers";
import { renderWithCommerce } from "../tests/test-utils";
import { CheckoutPage } from "./CheckoutPage";

// Filling the whole checkout form types about a hundred characters through
// jsdom. On a busy CI runner that takes longer than vitest's 5 seconds.
const FORM_TIMEOUT = 20_000;

describe("CheckoutPage", () => {
  beforeEach(() => {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...window.location, assign: vi.fn() },
    });
  });

  it("says there is nothing to check out for an empty cart", async () => {
    renderWithCommerce(<CheckoutPage />);
    expect(await screen.findByText("Nothing to check out")).toBeInTheDocument();
  });

  it(
    "sends a guest's email, address and note, never a price, then goes to pay",
    async () => {
      cartState.lines = [{ kind: "product", item: "lamp", quantity: 2 }];
      renderWithCommerce(<CheckoutPage />);
      await userEvent.type(
        await screen.findByLabelText("Email, for the confirmation"),
        "g@example.com",
      );
      await userEvent.type(screen.getByLabelText("Full name"), "Ines Moreau");
      await userEvent.type(screen.getByLabelText("Address"), "4 Rue des Lilas");
      await userEvent.type(screen.getByLabelText("City"), "Lyon");
      await userEvent.type(screen.getByLabelText("Postcode"), "69001");
      await userEvent.type(screen.getByLabelText("A note for the order (optional)"), "Ring twice");
      expect(screen.getByLabelText("Send it to a different address")).toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: "Place the order and pay" }));
      await vi.waitFor(() =>
        expect(window.location.assign).toHaveBeenCalledWith("https://pay.example.test/session/1"),
      );
      const [body] = checkoutCalls as Record<string, unknown>[];
      expect(body.email).toBe("g@example.com");
      expect(body.note).toBe("Ring twice");
      expect(body).not.toHaveProperty("total");
      expect((body.billing as Record<string, string>).city).toBe("Lyon");
    },
    FORM_TIMEOUT,
  );

  it("asks for no shipping address when nothing is sent", async () => {
    cartState.lines = [{ kind: "seat", item: "seat", quantity: 1 }];
    renderWithCommerce(<CheckoutPage />);
    expect(await screen.findByText("Billing address")).toBeInTheDocument();
    expect(screen.queryByLabelText("Send it to a different address")).not.toBeInTheDocument();
  });

  it("shows the server's word on a missing email", async () => {
    cartState.lines = [{ kind: "seat", item: "seat", quantity: 1 }];
    renderWithCommerce(<CheckoutPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Place the order and pay" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "An email address, for the confirmation.",
    );
  });

  it(
    "offers the ways to send it for the country, with the tax, and sends the one chosen",
    async () => {
      cartState.lines = [{ kind: "product", item: "lamp", quantity: 2 }];
      const { unmount } = renderWithCommerce(<CheckoutPage />);
      expect(
        await screen.findByText("The ways to send it show once you enter the country."),
      ).toBeInTheDocument();
      unmount();
      renderWithCommerce(<CheckoutPage defaultCountry="fr" />);
      await userEvent.type(
        await screen.findByLabelText("Email, for the confirmation"),
        "g@example.com",
      );
      await userEvent.type(screen.getByLabelText("Full name"), "Ines Moreau");
      await userEvent.type(screen.getByLabelText("Address"), "4 Rue des Lilas");
      await userEvent.type(screen.getByLabelText("City"), "Lyon");
      await userEvent.type(screen.getByLabelText("Postcode"), "69001");
      const pickup = await screen.findByRole("radio", { name: /Pickup in Lyon/ });
      expect(screen.getByRole("radio", { name: /Standard/ })).toBeChecked();
      expect(await screen.findByText("TVA 20%")).toBeInTheDocument();
      await userEvent.click(pickup);
      await waitFor(() =>
        expect(screen.getByText("Shipping (Pickup in Lyon)")).toBeInTheDocument(),
      );
      expect(screen.getByText("€38.40")).toBeInTheDocument(); // 32.00 + 20%
      await userEvent.click(screen.getByRole("button", { name: "Place the order and pay" }));
      await vi.waitFor(() => expect(checkoutCalls).toHaveLength(1));
      const [body] = checkoutCalls as Record<string, unknown>[];
      expect(body.shipping_method).toBe("m2");
    },
    FORM_TIMEOUT,
  );

  it("offers a deposit when every line allows one, and sends the choice", async () => {
    cartState.lines = [{ kind: "booking", item: "visit", quantity: 1 }];
    renderWithCommerce(<CheckoutPage defaultCountry="FR" />);
    await userEvent.type(
      await screen.findByLabelText("Email, for the confirmation"),
      "g@example.com",
    );
    await userEvent.type(screen.getByLabelText("Full name"), "Ines Moreau");
    await userEvent.type(screen.getByLabelText("Address"), "4 Rue des Lilas");
    await userEvent.type(screen.getByLabelText("City"), "Lyon");
    await userEvent.type(screen.getByLabelText("Postcode"), "69001");
    const deposit = await screen.findByLabelText(/Pay a deposit/);
    expect(screen.getByLabelText(/Pay in full/)).toBeChecked();
    expect(screen.getByText(/later by the link we email you/)).toBeInTheDocument();
    await userEvent.click(deposit);
    await userEvent.click(
      screen.getByRole("button", { name: "Place the order and pay the deposit" }),
    );
    await vi.waitFor(() => expect(checkoutCalls).toHaveLength(1));
    const [body] = checkoutCalls as Record<string, unknown>[];
    expect(body.pay).toBe("deposit");
  });

  it("offers no deposit when a line allows none", async () => {
    cartState.lines = [
      { kind: "booking", item: "visit", quantity: 1 },
      { kind: "seat", item: "seat", quantity: 1 },
    ];
    renderWithCommerce(<CheckoutPage defaultCountry="FR" />);
    expect(await screen.findByText("Billing address")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("TVA 20%")).toBeInTheDocument());
    expect(screen.queryByLabelText(/Pay a deposit/)).not.toBeInTheDocument();
  });

  it("says when the order cannot be sent to the country", async () => {
    cartState.lines = [{ kind: "product", item: "lamp", quantity: 1 }];
    renderWithCommerce(<CheckoutPage defaultCountry="US" />);
    expect(await screen.findByText("We do not send orders to US yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Place the order and pay" })).toBeDisabled();
  });
});
