import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { cartState } from "../tests/msw/handlers";
import { renderWithCommerce } from "../tests/test-utils";
import { CartPage } from "./CartPage";

describe("CartPage", () => {
  it("shows an empty cart with a way to start shopping", async () => {
    const { navigated } = renderWithCommerce(<CartPage />);
    expect(await screen.findByText("Your cart is empty")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Start shopping" }));
    expect(navigated).toEqual(["/shop"]);
  });

  it("lists each line with its sale price, the subtotal and checkout", async () => {
    cartState.lines = [{ kind: "product", item: "lamp", quantity: 2 }];
    const { navigated } = renderWithCommerce(<CartPage />);
    expect(await screen.findByRole("link", { name: "Brass Lamp" })).toHaveAttribute(
      "href",
      "/shop/lamp",
    );
    expect(screen.getAllByText("€32.00")).toHaveLength(3); // the line, the items, the total
    expect(screen.getByText("With the address")).toBeInTheDocument(); // shipping at checkout
    expect(screen.getByText("€20.00").closest(".line-through")).not.toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Check out" }));
    expect(navigated).toEqual(["/checkout"]);
  });

  it("removes a line and says why a line cannot be bought", async () => {
    cartState.lines = [
      { kind: "product", item: "lamp", quantity: 5 },
      { kind: "seat", item: "seat", quantity: 1 },
    ];
    renderWithCommerce(<CartPage />);
    expect(await screen.findByText("Only 3 left.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check out" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Remove Brass Lamp" }));
    await waitFor(() => expect(screen.queryByText("Brass Lamp")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Check out" })).toBeEnabled();
  });

  it("applies a coupon, says why a code is refused, and takes it off", async () => {
    cartState.lines = [{ kind: "product", item: "lamp", quantity: 2 }];
    renderWithCommerce(<CartPage />);
    const code = await screen.findByLabelText("Coupon code");
    await userEvent.type(code, "nope");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No coupon has that code.");
    await userEvent.clear(screen.getByLabelText("Coupon code"));
    await userEvent.type(screen.getByLabelText("Coupon code"), "save10");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(await screen.findByText("Discount (SAVE10)")).toBeInTheDocument();
    expect(screen.getByText("€28.80")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Remove the coupon" }));
    await waitFor(() => expect(screen.queryByText("Discount (SAVE10)")).not.toBeInTheDocument());
  });
});
