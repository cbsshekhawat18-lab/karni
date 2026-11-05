## General rules

- JSON in and out. Every URL ends with a slash. Paths below are under `/api/`.
- A list endpoint answers a JSON array or an object with a `results` array (a paginated list is fine).
- Every object has an `id` (a number or a string, any scheme). Money fields are decimals with two places, as a string (`"12.50"`) or a number. Times are ISO 8601.
- Create answers 201 with the new object. A bad request answers 400. A role that may not do something gets 403. An object the user may not see answers 404 or 403. Without a valid token every endpoint except sign-in answers 401 or 403.

## Sign-in and accounts

- `POST /api/auth/login/` with `{"email", "password"}` answers 200 with JSON that has a token in `access` (or `token`). The client sends it as `Authorization: Bearer <token>`. A wrong password answers 400 or 401.
- The management command `python manage.py create_account EMAIL PASSWORD ROLE` creates the account with that role, or, when the email exists, sets its password and role. It exits 0. The checks use it to make their accounts.
- Roles: `customer` and `staff`.

## Catalog

- `GET /api/categories/` and `GET /api/products/` (any signed-in user). `?category=<id>` filters products. `GET /api/products/<id>/` shows one.
- Staff create, `PATCH` and `DELETE` categories and products. A customer gets 403.
- A category shows `id`, `name` (required). A product shows `id`, `category` (the category id), `name` (required), `price` (not negative), `stock` (a whole number, not negative).

## Cart

Each customer has one cart.

- `GET /api/cart/` answers `{"items": [{"id", "product", "quantity", "line_total"}], "total"}`. `product` is the product id. `line_total` is price times quantity and `total` is their sum.
- `POST /api/cart/items/` with `{"product", "quantity"}` adds to the cart and answers 201 with the item. Adding a product that is already in the cart adds to its quantity. A quantity below 1 or an unknown product answers 400.
- `DELETE /api/cart/items/<id>/` removes an item (204).

## Checkout and orders

- `POST /api/cart/checkout/` turns the cart into an order, opens its payment, empties the cart and answers 201 with the order. An empty cart answers 400. When any product has less stock than the quantity in the cart it answers 409 and changes nothing. A successful checkout takes the quantities off the products' stock.
- An order shows `id`, `status`, `total`, `items` (`[{"product", "quantity", "unit_price"}]`, with the price at checkout time) and `payment` (the payment, `{"id", "status", "amount"}`). Statuses: `pending`, `paid`, `shipped`, `refunded`. A new order is `pending`.
- `GET /api/orders/` lists the signed-in customer's own orders, staff see every order. `GET /api/orders/<id>/` shows one. Another customer's order answers 404 or 403. Customers cannot create or change orders directly (405 or 403).

## Payments and refunds (test provider)

- `POST /api/payments/<id>/confirm/` (the payment's owner, or staff) is what the test provider calls when the customer has paid. It sets the payment to `succeeded` and its order to `paid`. Confirming twice is harmless (200). A real provider would send a webhook, the confirm endpoint stands in for it.
- `POST /api/orders/<id>/ship/` (staff only) moves a `paid` order to `shipped`. Any other status answers 400.
- `POST /api/orders/<id>/refund/` (staff only) refunds a `paid` or `shipped` order through the test provider. The order becomes `refunded`, its payment becomes `refunded` and the products' stock goes back up by the order's quantities. A `pending` or already `refunded` order answers 400 and changes nothing.
