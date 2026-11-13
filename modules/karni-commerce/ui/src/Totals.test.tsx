import { screen } from "@testing-library/react";
import { renderWithCommerce as render } from "../tests/test-utils";
import { couponLimits, registerCouponLimit } from "./couponLimits";
import { Totals } from "./Totals";

describe("Totals", () => {
  it("says the tax is included when the prices hold it, and free shipping in words", () => {
    render(
      <Totals
        currency="EUR"
        subtotal="24.00"
        discount="0.00"
        shipping="0.00"
        shippingMethod="Pickup"
        taxLines={[{ name: "VAT", rate: "20.0000", amount: "4.00" }]}
        pricesIncludeTax
        total="24.00"
      />,
    );
    expect(screen.getByText("VAT 20% (included)")).toBeInTheDocument();
    expect(screen.getByText("Free")).toBeInTheDocument();
    expect(screen.queryByText(/Discount/)).not.toBeInTheDocument();
  });

  it("asks for the address before it knows the shipping", () => {
    render(<Totals subtotal="10.00" shipping={null} total="10.00" currency="EUR" />);
    expect(screen.getByText("With the address")).toBeInTheDocument();
  });
});

describe("registerCouponLimit", () => {
  it("offers each limit once, the last registration winning", () => {
    registerCouponLimit({ key: "categories", label: "Categories", resource: "categories" });
    registerCouponLimit({ key: "categories", label: "Product groups", resource: "categories" });
    expect(couponLimits().filter((limit) => limit.key === "categories")).toEqual([
      { key: "categories", label: "Product groups", resource: "categories" },
    ]);
  });
});
