import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { cartState, ITEMS } from "../tests/msw/handlers";
import { renderWithCommerce } from "../tests/test-utils";
import { AddToCart } from "./AddToCart";

describe("AddToCart", () => {
  it("adds the quantity on top of what the cart holds", async () => {
    cartState.lines = [{ kind: "product", item: "lamp", quantity: 1 }];
    renderWithCommerce(<AddToCart kind="product" item="lamp" name="Brass Lamp" available={3} />);
    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "2" } });
    await userEvent.click(screen.getByRole("button", { name: "Add to cart" }));
    await waitFor(() =>
      expect(cartState.lines).toEqual([{ kind: "product", item: "lamp", quantity: 3 }]),
    );
    expect(await screen.findByText("Brass Lamp is in your cart")).toBeInTheDocument();
  });

  it("shows the server's refusal", async () => {
    cartState.lines = [{ kind: "product", item: "lamp", quantity: 3 }];
    renderWithCommerce(<AddToCart kind="product" item="lamp" />);
    await userEvent.click(screen.getByRole("button", { name: "Add to cart" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Only 3 left.");
  });

  it("is off when nothing is left", () => {
    ITEMS.lamp.available = 0;
    renderWithCommerce(<AddToCart kind="product" item="lamp" available={0} />);
    expect(screen.getByRole("button", { name: "Sold out" })).toBeDisabled();
  });
});
