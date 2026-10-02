import { screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { API_BASE, paymentFixture, server } from "../tests/msw/server";
import { renderWithKarni } from "../tests/test-utils";
import { PaymentStatus } from "./PaymentStatus";

describe("PaymentStatus", () => {
  it("renders the status badge and formatted amount", async () => {
    renderWithKarni(<PaymentStatus paymentId="pay_1" />);

    expect(await screen.findByText("succeeded")).toBeInTheDocument();
    const wrapper = screen.getByText("succeeded").closest("[data-karni-role=payment-status]");
    expect(wrapper).not.toBeNull();
    expect(wrapper).toHaveAttribute("data-status", "succeeded");
    // Amount rendering is locale-dependent; assert on the digits.
    expect(wrapper).toHaveTextContent(/49/);
  });

  it("renders a readable label for underscored statuses", async () => {
    server.use(
      http.get(`${API_BASE}/payments/pay_refund/`, () =>
        HttpResponse.json({ ...paymentFixture, id: "pay_refund", status: "partially_refunded" }),
      ),
    );
    renderWithKarni(<PaymentStatus paymentId="pay_refund" />);

    expect(await screen.findByText("partially refunded")).toBeInTheDocument();
  });

  it("polls the payment while a poll interval is set", async () => {
    let requests = 0;
    server.use(
      http.get(`${API_BASE}/payments/pay_poll/`, () => {
        requests += 1;
        return HttpResponse.json({ ...paymentFixture, id: "pay_poll", status: "processing" });
      }),
    );
    renderWithKarni(<PaymentStatus paymentId="pay_poll" poll={50} />);

    expect(await screen.findByText("processing")).toBeInTheDocument();
    await waitFor(() => expect(requests).toBeGreaterThanOrEqual(3), { timeout: 3000 });
  });

  it("fetches exactly once when poll is off", async () => {
    let requests = 0;
    server.use(
      http.get(`${API_BASE}/payments/pay_once/`, () => {
        requests += 1;
        return HttpResponse.json({ ...paymentFixture, id: "pay_once" });
      }),
    );
    renderWithKarni(<PaymentStatus paymentId="pay_once" />);

    expect(await screen.findByText("succeeded")).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 200));
    expect(requests).toBe(1);
  });

  it("supports the escape hatches: labels, classes, formatAmount, render prop", async () => {
    renderWithKarni(
      <PaymentStatus
        paymentId="pay_1"
        statusLabels={{ succeeded: "Paid" }}
        statusClassNames={{ succeeded: "bg-secondary text-secondary-foreground" }}
        formatAmount={(payment) => `${payment.amount} ${payment.currency.toUpperCase()} flat`}
      />,
    );

    const badge = await screen.findByText("Paid");
    expect(badge.className).toContain("bg-secondary");
    expect(screen.getByText("49.00 USD flat")).toBeInTheDocument();

    renderWithKarni(
      <PaymentStatus paymentId="pay_1">
        {(payment) => <strong>custom {payment.status}</strong>}
      </PaymentStatus>,
    );
    expect(await screen.findByText("custom succeeded")).toBeInTheDocument();
  });

  it("renders the error fallback when the fetch fails", async () => {
    server.use(
      http.get(`${API_BASE}/payments/pay_missing/`, () =>
        HttpResponse.json({ detail: "Not found." }, { status: 404 }),
      ),
    );
    renderWithKarni(<PaymentStatus paymentId="pay_missing" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Payment could not be loaded.");
  });
});
