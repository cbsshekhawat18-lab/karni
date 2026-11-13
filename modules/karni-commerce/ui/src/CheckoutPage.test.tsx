import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { cartState, checkoutCalls } from "../tests/msw/handlers";
import { renderWithCommerce } from "../tests/test-utils";
import { CheckoutPage } from "./CheckoutPage";

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

  it("sends a guest's email, address and note, never a price, then goes to pay", async () => {
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
  });

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

  it("offers the ways to send it for the country, with the tax, and sends the one chosen", async () => {
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
    await waitFor(() => expect(screen.getByText("Shipping (Pickup in Lyon)")).toBeInTheDocument());
    expect(screen.getByText("€38.40")).toBeInTheDocument(); // 32.00 + 20%
    await userEvent.click(screen.getByRole("button", { name: "Place the order and pay" }));
    await vi.waitFor(() => expect(checkoutCalls).toHaveLength(1));
    const [body] = checkoutCalls as Record<string, unknown>[];
    expect(body.shipping_method).toBe("m2");
  });

  it("says when the order cannot be sent to the country", async () => {
    cartState.lines = [{ kind: "product", item: "lamp", quantity: 1 }];
    renderWithCommerce(<CheckoutPage defaultCountry="US" />);
    expect(await screen.findByText("We do not send orders to US yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Place the order and pay" })).toBeDisabled();
  });
});
