from __future__ import annotations

from typing import Any

from conftest import BASE, Api, money, rows, unique


def make_product(staff: Api, stock: int = 10, price: str = "12.50") -> dict[str, Any]:
    category = staff.post("categories/", {"name": unique("cat")})
    assert category.status_code == 201, category.text
    product = staff.post(
        "products/",
        {"category": category.json()["id"], "name": unique("prod"), "price": price, "stock": stock},
    )
    assert product.status_code == 201, product.text
    return product.json()


def clear_cart(customer: Api) -> None:
    for item in customer.get("cart/").json()["items"]:
        customer.delete(f"cart/items/{item['id']}/")


def checkout(customer: Api, product: dict[str, Any], quantity: int) -> dict[str, Any]:
    clear_cart(customer)
    added = customer.post("cart/items/", {"product": product["id"], "quantity": quantity})
    assert added.status_code == 201, added.text
    order = customer.post("cart/checkout/")
    assert order.status_code == 201, order.text
    return order.json()


def stock_of(api: Api, product: dict[str, Any]) -> int:
    return api.get(f"products/{product['id']}/").json()["stock"]


def test_sign_in_and_protection(anonymous):
    assert anonymous.get(f"{BASE}/api/products/").status_code in (401, 403)
    assert anonymous.get(f"{BASE}/api/cart/").status_code in (401, 403)
    bad = anonymous.post(
        f"{BASE}/api/auth/login/", json={"email": "staff@bench.test", "password": "wrong"}
    )
    assert bad.status_code in (400, 401)


def test_staff_manage_the_catalog_and_customers_cannot(api):
    staff, customer = api("staff"), api("customer")
    product = make_product(staff)
    assert money(product["price"]) == money("12.50") and product["stock"] == 10
    assert customer.post("categories/", {"name": unique("cat")}).status_code == 403
    assert (
        customer.post(
            "products/", {"category": product["category"], "name": "x", "price": "1.00", "stock": 1}
        ).status_code
        == 403
    )
    assert customer.patch(f"products/{product['id']}/", {"stock": 99}).status_code == 403
    assert staff.patch(f"products/{product['id']}/", {"stock": 7}).json()["stock"] == 7
    assert staff.post("products/", {"name": "", "price": "1", "stock": 1}).status_code == 400
    assert (
        staff.post(
            "products/",
            {"category": product["category"], "name": unique("p"), "price": "1", "stock": -1},
        ).status_code
        == 400
    )


def test_customers_list_and_filter_products(api):
    staff, customer = api("staff"), api("customer")
    product = make_product(staff)
    found = rows(customer.get("products/", params={"category": product["category"]}))
    assert [p["id"] for p in found] == [product["id"]]
    assert customer.get(f"products/{product['id']}/").status_code == 200
    assert any(c["id"] == product["category"] for c in rows(customer.get("categories/")))


def test_cart_adds_totals_and_removes(api):
    staff, customer = api("staff"), api("customer")
    product = make_product(staff, price="10.00")
    other = make_product(staff, price="2.25")
    clear_cart(customer)
    assert customer.get("cart/").json()["items"] == []
    first = customer.post("cart/items/", {"product": product["id"], "quantity": 2})
    assert first.status_code == 201, first.text
    assert (
        customer.post("cart/items/", {"product": product["id"], "quantity": 1}).status_code == 201
    )
    customer.post("cart/items/", {"product": other["id"], "quantity": 2})
    cart = customer.get("cart/").json()
    by_product = {i["product"]: i for i in cart["items"]}
    assert by_product[product["id"]]["quantity"] == 3
    assert money(by_product[product["id"]]["line_total"]) == money("30.00")
    assert money(cart["total"]) == money("34.50")
    item = by_product[other["id"]]
    assert customer.delete(f"cart/items/{item['id']}/").status_code == 204
    assert money(customer.get("cart/").json()["total"]) == money("30.00")


def test_cart_refuses_bad_quantities_and_products(api):
    staff, customer = api("staff"), api("customer")
    product = make_product(staff)
    assert (
        customer.post("cart/items/", {"product": product["id"], "quantity": 0}).status_code == 400
    )
    assert (
        customer.post("cart/items/", {"product": product["id"], "quantity": -2}).status_code == 400
    )
    assert customer.post("cart/items/", {"product": 987654321, "quantity": 1}).status_code == 400


def test_carts_are_private(api):
    staff, one, two = api("staff"), api("customer"), api("customer2")
    product = make_product(staff)
    clear_cart(one)
    clear_cart(two)
    one.post("cart/items/", {"product": product["id"], "quantity": 1})
    assert two.get("cart/").json()["items"] == []


def test_checkout_makes_a_pending_order_with_a_payment(api):
    staff, customer = api("staff"), api("customer")
    product = make_product(staff, stock=5, price="20.00")
    order = checkout(customer, product, 2)
    assert order["status"] == "pending"
    assert money(order["total"]) == money("40.00")
    assert [(i["product"], i["quantity"]) for i in order["items"]] == [(product["id"], 2)]
    assert money(order["items"][0]["unit_price"]) == money("20.00")
    assert order["payment"]["status"] == "pending"
    assert money(order["payment"]["amount"]) == money("40.00")
    assert stock_of(staff, product) == 3
    assert customer.get("cart/").json()["items"] == []


def test_checkout_price_is_fixed_at_checkout_time(api):
    staff, customer = api("staff"), api("customer")
    product = make_product(staff, price="5.00")
    order = checkout(customer, product, 1)
    staff.patch(f"products/{product['id']}/", {"price": "9.00"})
    again = customer.get(f"orders/{order['id']}/").json()
    assert money(again["total"]) == money("5.00")
    assert money(again["items"][0]["unit_price"]) == money("5.00")


def test_checkout_refuses_an_empty_cart(api):
    customer = api("customer")
    clear_cart(customer)
    assert customer.post("cart/checkout/").status_code == 400


def test_checkout_refuses_more_than_the_stock_and_changes_nothing(api):
    staff, customer = api("staff"), api("customer")
    product = make_product(staff, stock=2)
    clear_cart(customer)
    customer.post("cart/items/", {"product": product["id"], "quantity": 3})
    before = len(rows(customer.get("orders/")))
    assert customer.post("cart/checkout/").status_code == 409
    assert stock_of(staff, product) == 2
    assert len(rows(customer.get("orders/"))) == before
    assert len(customer.get("cart/").json()["items"]) == 1


def test_orders_are_private_and_staff_see_all(api):
    staff, one, two = api("staff"), api("customer"), api("customer2")
    order = checkout(one, make_product(staff), 1)
    assert order["id"] in [o["id"] for o in rows(one.get("orders/"))]
    assert order["id"] not in [o["id"] for o in rows(two.get("orders/"))]
    assert two.get(f"orders/{order['id']}/").status_code in (403, 404)
    assert order["id"] in [o["id"] for o in rows(staff.get("orders/"))]
    assert staff.get(f"orders/{order['id']}/").status_code == 200


def test_customers_cannot_write_orders_directly(api):
    staff, customer = api("staff"), api("customer")
    order = checkout(customer, make_product(staff), 1)
    assert customer.patch(f"orders/{order['id']}/", {"status": "shipped"}).status_code in (403, 405)
    assert customer.delete(f"orders/{order['id']}/").status_code in (403, 405)
    assert customer.post("orders/", {"items": []}).status_code in (403, 405)


def test_confirming_the_payment_pays_the_order(api):
    staff, customer = api("staff"), api("customer")
    order = checkout(customer, make_product(staff), 1)
    paid = customer.post(f"payments/{order['payment']['id']}/confirm/")
    assert paid.status_code == 200, paid.text
    assert customer.get(f"orders/{order['id']}/").json()["status"] == "paid"
    assert customer.get(f"orders/{order['id']}/").json()["payment"]["status"] == "succeeded"
    assert customer.post(f"payments/{order['payment']['id']}/confirm/").status_code == 200
    assert customer.get(f"orders/{order['id']}/").json()["status"] == "paid"


def test_another_customer_cannot_confirm_a_payment(api):
    staff, one, two = api("staff"), api("customer"), api("customer2")
    order = checkout(one, make_product(staff), 1)
    assert two.post(f"payments/{order['payment']['id']}/confirm/").status_code in (403, 404)
    assert one.get(f"orders/{order['id']}/").json()["status"] == "pending"


def test_staff_ship_only_paid_orders(api):
    staff, customer = api("staff"), api("customer")
    order = checkout(customer, make_product(staff), 1)
    assert staff.post(f"orders/{order['id']}/ship/").status_code == 400
    customer.post(f"payments/{order['payment']['id']}/confirm/")
    assert customer.post(f"orders/{order['id']}/ship/").status_code == 403
    shipped = staff.post(f"orders/{order['id']}/ship/")
    assert shipped.status_code == 200, shipped.text
    assert staff.get(f"orders/{order['id']}/").json()["status"] == "shipped"
    assert staff.post(f"orders/{order['id']}/ship/").status_code == 400


def test_refund_returns_the_stock_and_marks_the_order(api):
    staff, customer = api("staff"), api("customer")
    product = make_product(staff, stock=6)
    order = checkout(customer, product, 4)
    assert stock_of(staff, product) == 2
    assert staff.post(f"orders/{order['id']}/refund/").status_code == 400  # still pending
    customer.post(f"payments/{order['payment']['id']}/confirm/")
    assert customer.post(f"orders/{order['id']}/refund/").status_code == 403
    refunded = staff.post(f"orders/{order['id']}/refund/")
    assert refunded.status_code == 200, refunded.text
    final = staff.get(f"orders/{order['id']}/").json()
    assert final["status"] == "refunded"
    assert final["payment"]["status"] == "refunded"
    assert stock_of(staff, product) == 6
    assert staff.post(f"orders/{order['id']}/refund/").status_code == 400
    assert stock_of(staff, product) == 6


def test_a_shipped_order_can_be_refunded(api):
    staff, customer = api("staff"), api("customer")
    order = checkout(customer, make_product(staff), 1)
    customer.post(f"payments/{order['payment']['id']}/confirm/")
    staff.post(f"orders/{order['id']}/ship/")
    assert staff.post(f"orders/{order['id']}/refund/").status_code == 200
    assert staff.get(f"orders/{order['id']}/").json()["status"] == "refunded"
