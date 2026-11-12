import { screen } from "@testing-library/react";
import { renderWithCommerce } from "../tests/test-utils";
import { OrderPage } from "./OrderPage";
import { MyOrders } from "./MyOrders";

describe("OrderPage", () => {
  it("shows a paid order with its lines, delivery and addresses to the guest with its key", async () => {
    renderWithCommerce(<OrderPage number="1001" orderKey="k1" />);
    expect(await screen.findByRole("heading", { name: "Order 1001" })).toBeInTheDocument();
    expect(screen.getByText("Paid")).toBeInTheDocument();
    expect(screen.getByText(/Your order is confirmed/)).toBeInTheDocument();
    expect(screen.getByText(/Tracking TR123/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Brass Lamp" })).toHaveAttribute("href", "/shop/lamp");
    expect(screen.getAllByText("€32.00").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Pay now" })).not.toBeInTheDocument();
  });

  it("says so without the key", async () => {
    renderWithCommerce(<OrderPage number="1001" />);
    expect(await screen.findByRole("link", { name: "Your orders" })).toHaveAttribute(
      "href",
      "/orders",
    );
    expect(screen.queryByRole("heading", { name: "Order 1001" })).not.toBeInTheDocument();
  });
});

describe("MyOrders", () => {
  it("lists the person's orders as links", async () => {
    renderWithCommerce(<MyOrders />);
    expect(await screen.findByRole("link", { name: /Order 1001/ })).toHaveAttribute(
      "href",
      "/orders/1001",
    );
  });
});
