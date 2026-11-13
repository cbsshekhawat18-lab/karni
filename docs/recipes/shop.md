---
description: "The shop recipe: a storefront with categories, products in sizes and colours, digital products, reviews, a wishlist, a cart with coupons, checkout with shipping methods and tax through karni-commerce and karni-payments, order emails a manager edits, parcels with tracking, invoices and packing slips, reports with CSV, abandoned carts, settings without code and a staff home. What each role does, how to change it, and what it does not do."
---

# Recipe: online shop

!!! warning "Experimental"
    Recipes are [experimental](../stability.md#experimental-names). See
    [recipes](index.md).

An online shop that a small business can open with: a storefront anyone can
browse, a cart that a visitor keeps and that joins their account when they
sign in, checkout as a guest or signed in, payment at the provider, an order
page, an invoice and emails for the buyer, parcels that staff send with a
tracking number, files a buyer downloads, and the settings, emails, reports
and abandoned carts a manager runs the shop with.

```sh
karni new "Corner Shop" --recipe shop
```

The cart, checkout, orders, payments and refunds come from
[karni-commerce](../commerce.md), the same order path a booking or a course
would use in the same project. The shop adds its catalogue, its stock rules
and its parcels.

## What each person does

### A visitor

- Browses the storefront at `/shop`: the categories, featured products and
  new arrivals. `/shop/products` is the catalogue, with search, a category
  (and its sub-categories), a price range, the sort order (name, newest,
  price) and pages, all kept in the address so a link finds them again.
- Opens a product at `/shop/products/<slug>`: its pictures, the price (the
  sale price next to the regular one while a sale runs), how many are left,
  its rating and reviews, and the description. Every page has a title and a
  description for search engines.
- Picks the options of a product sold in several ways (a size, a colour):
  the price, what is left, the SKU and the picture follow the choice, and a
  value no way for sale has is off. A card shows the price range ("From
  $14.00") and opens the product to choose.
- Sees related products under a product (the ones staff chose, then the
  same category's best rated) and the products this browser looked at
  last.
- Adds products to the cart from a card or a product page. The mini cart in
  the header shows the count and the first lines. `/cart` changes quantities
  and takes lines out, and says when a line cannot be bought (sold out, fewer
  left, no longer for sale).
- Types a coupon code at the cart or at checkout. The cart says what it
  takes off, or why it does not work (expired, used up, a minimum spend,
  nothing in the cart it applies to).
- Buys a digital product (a printable planner, a pattern): it says "Digital
  download" instead of what is left, needs no shipping, and once paid its
  files are on the order page and in an email, each by a signed link that
  works a set number of times (Settings, Shop: 5) for a set number of days
  (30). After that, or once the product is refunded, the link says why it
  stopped.
- Checks out at `/checkout` as a guest: an email, the billing address, a
  different shipping address if they want, and a note. Once the country is
  in, checkout offers the ways to send it there (a flat rate, free above an
  amount, local pickup) with their prices, and shows the tax lines and the
  total. The order holds the
  products for 30 minutes while they pay at the provider. Back from the
  provider, the order page confirms the payment, and the confirmation email
  arrives with a link to the order.

### A customer

- Signs in at `/signin` with a code sent by email (a new address gets an
  account that way) or with a password. The cart they filled as a visitor
  joins their account's cart, and orders they placed as a guest with the
  same, verified email become theirs.
- Checks out without typing their email, after accepting the shop's terms of
  sale (`features.terms`).
- Prints the invoice of a paid order (`/orders/<number>/invoice`, from the
  order page), or saves it as PDF from the print dialog.
- Sees their orders at `/orders` and each one at `/orders/<number>`: where
  the money stands, where the parcel is (being prepared, shipped with its
  tracking number, delivered), the lines with their options, the coupon,
  the shipping, the tax and the addresses. `/account` shows their orders
  and their name.
- Reviews a product once its parcel reached them: a rating from one to five
  stars and a few words. The review shows once staff approve it, marked as
  bought here.
- Keeps products for later on `/wishlist` (Add to wishlist on a product).

### Staff (`shop-staff`)

- Their home `/` shows the tiles of their role: orders to fulfil and parcels
  on their way (each opens the shipments it counts), products sold out and
  running low (each product at its own level), revenue today, in 7 and in
  30 days with a chart by day, the latest orders and the best sellers of 30
  days. A customer has no tiles: their home is the storefront.
- `/orders` lists every order, newest first: search by number, email or name,
  filter by state and by the days it was placed, sort, page and export.
  An order's page (`/orders/<number>`) shows the buyer (with their orders and
  what they spent), the lines, payments and refunds, the addresses, the
  buyer's note, the notes (internal, or to the customer, who gets it by
  email and on their order page) and the history of its money. Its parcel
  is there too: mark it shipped with its tracking number, then delivered.
  The buyer gets an email at each step.
- Cancel an order. A paid one puts its products back on the shelf and its
  money goes back through the provider.
- Place an order by hand for a customer who called (`/orders/new`): find the
  products, set the quantities, type the customer and the address, a coupon
  and the way to send it. The totals (the discount, the shipping, the tax)
  show before the order is placed. The server prices it and holds the stock
  for two days, and the customer gets the link to pay.
- `/customers` lists who bought, how often and for how much, and each
  customer's page their orders and addresses.
- `/reviews` lists the reviews, newest first, with the ones waiting for
  approval counted on the home page. A review's page approves or rejects
  it.
- A product's page lists its variations (each with its values, SKU, price,
  stock and picture). `/attributes` holds the options (Size, Colour) and
  their values.
- `/shipments` lists the parcels, each with its order's number linking to
  the order. An order's page prints its packing slip (what goes in the
  parcel and where, no prices) and its invoice.
- `/abandoned-carts` lists the carts with items nobody touched for an hour
  (Settings, Checkout): who left it when known (a customer, or the email a
  visitor typed at checkout), what is in it and what it comes to.
- `/downloads` lists who may download which file, how often they did and
  until when.
- Manage the catalogue: `/products` with search, filters, CSV and XLSX export,
  **Import** (upload a CSV, check the preview with each row's problems, then
  commit) and bulk changes (select products, then set the price, the sale
  price, the stock, the low-stock level, active or featured). A product's
  page has its pictures (add, order and remove them), and its form the price
  and sale dates, the stock, the low-stock level and whether it takes
  backorders. Categories in a tree, and tags.

### A manager (`shop-manager`) and an admin (`admin`)

- Everything staff do, and refunds: all or part of an order, by items (with
  them back in stock or not) or by an amount. The refund goes through the
  payment provider, and the order shows part refunded or refunded once the
  provider confirms it.
- `/coupons`: codes with a percent, an amount or free shipping, a minimum
  spend, start and end dates, uses allowed in all and per customer, and the
  products or categories they apply to (picked by name).
- `/shipping`: the zones (countries, and regions or postcode starts) and
  each zone's methods (flat rate, free above an amount, local pickup).
- `/tax-rates`: the rates by country and region, and whether they apply to
  shipping.
- `/reports`: sales by date (by day, week or month), by item, by category,
  the coupons used, and the stock (each product and variation: on the shelf,
  held by orders, left, its low-stock level and its state), each for the
  days chosen, with its totals and a CSV file. Staff do not see them
  (`karni_commerce.order:report`).
- `/settings`, with no code:
    - Details: the shop's name (in the header, the footer, the emails and on
      invoices), legal name, address, phone, contact email, tax number, the
      email sender and where answers go, and how money shows its currency.
    - Checkout: guest checkout or sign in first, whether buyers tick the
      terms of sale (and where the terms are), the invoice prefix and footer,
      who gets the new-order email, and when a cart counts as abandoned.
    - Shop: the low-stock level, whether shoppers see how many are left,
      whether sold out products leave the catalogue, whether reviews wait for
      approval, how many related products show, and how often and how long
      a file may be downloaded.
    - Emails: every email the shop sends, each with a switch and its text.
      Edit opens the subject and the text with the merge fields it may use
      (`{{ order.number }}`, `{{ shipment.tracking_number }}`), a preview
      and Back to the default. The next email of that kind is the edited
      one. The sign-in code and the password emails are always sent.
- Each role sees only the buttons it may use: staff see no Refund, a role
  that may only read sees no New, Edit or Import.

The demo logins (password `karni-password`) are `demo@example.com` (admin),
`manager@example.com`, `staff@example.com` and `customer@example.com`.

## The rules

- Stock is held at checkout, taken when the order is paid, and given back
  when the payment fails, the order is cancelled, or the 30 minutes pass
  without a payment. A refund with "back in stock" puts the items back too.
  The database refuses stock below zero, and two buyers of the last item
  never both get it (`karni.capacity`).
- A product that takes backorders may be ordered past what is left: checkout
  holds what is on the shelf and the rest waits for new stock. Only what
  came off the shelf goes back on a cancel or a refund with "back in stock".
- A product runs low at its own low-stock level, or at the shop's (Settings,
  Shop: 3) when it has none: staff get an email and the home tile lists it.
- A product sold in variations has no stock of its own: its stock is its
  active variations' added up, everywhere (the cards, the lists and their
  filters, the home tiles, the API). Its form refuses another figure: change
  each variation's stock.
- A product's `available` is the stock no order holds. Changing `stock` in
  the back office moves `available` by the same amount.
- The price, name and SKU of each line are copied to the order at checkout,
  and every total is worked out on the server. Checkout never takes a price
  from the browser.
- An order's status is its money only: waiting for payment, paid, payment
  failed, cancelled, part refunded, refunded. The parcel has its own:
  processing, shipped, delivered or cancelled. A payment that arrives after
  the order stopped waiting goes back at once.
- A product with active variations is bought by one of them: the cart
  refuses it without its options, and the variation's own stock is held,
  taken and given back as a product's is. Two buyers of the last of one
  size never both get it. The product's own stock is not used for it.
- A coupon is checked when it is applied and again at checkout, inside the
  checkout's transaction, so its limits hold with two buyers at once. A
  cancelled order gives its use back.
- The total is the items less the coupon, plus the shipping, plus the tax
  (prices are entered without tax; `modules.commerce: {prices_include_tax:
  true}` when they include it). The order keeps each part and its tax lines,
  and a refund by items gives back what those items cost after the discount
  and with their tax.
- A review needs a paid order of the product whose parcel was delivered,
  one per customer and product. It waits for staff (Settings, Shop), and a
  product's rating counts its approved reviews only.
- A digital product holds no stock and is never sold out. A download link is
  signed, so it cannot be made up. Each use is counted while the row is
  locked, so two clicks at once never pass the limit. It stops when the
  order is cancelled or refunded, or the product's line is refunded.
- With guest checkout off, a visitor signs in before checkout (the server
  refuses a guest's order). With the terms on, an order without them ticked
  is refused.
- Order numbers count up from 1001, and an invoice is numbered when its
  order is paid, from 1001, with no gap. It keeps the shop's details of that
  day.
- Every move of an order and a parcel is in its change history.

## Emails

| Email | To | When |
|---|---|---|
| `commerce.order_paid` | the buyer | the order is paid |
| `commerce.new_order` | `KARNI_COMMERCE_STAFF_EMAILS` | an order is paid |
| `commerce.order_cancelled` | the buyer | the order is cancelled |
| `commerce.order_refunded` | the buyer | a refund went through |
| `shop.shipment_shipped` | the buyer | the parcel left, with its tracking number |
| `shop.shipment_delivered` | the buyer | the parcel arrived |
| `shop.downloads_ready` | the buyer | a paid order has files: the links |
| `shop.low_stock` | `SHOP_STAFF_EMAILS` (else the Checkout staff emails) | an order leaves a product at its low-stock level |
| `commerce.order_note`, `commerce.payment_request` | the buyer | staff wrote them a note, or placed an order for them |
| `accounts.login_code`, `accounts.reset_password` | the person | the sign-in code, the link to a new password |

The paid email is the buyer's confirmation that the order is in and being
prepared, so there is no separate "processing" email. In development every
email prints in the console. A manager rewrites any of them on the Settings
page (Emails) and switches one off there. A project can also put a template
of the same path under its templates (`shop/email/shipment_shipped_body.txt`)
or list a kind in `KARNI_MAIL_DISABLED_KINDS`.

## Trying it without a payment account

`modules.payments.provider` is `stripe`, with the keys in `.env`. To try the
whole journey on your machine without an account, put
`KARNI_PAYMENTS_PROVIDER=test` in `.env`: the environment wins over
karni.yaml's provider, so no file changes. While `DEBUG` is on, checkout then
sends the buyer to a test page with Pay and Decline, which settles the payment
the way the provider's webhook would. Take the line out before the shop opens.

The API answers a visitor 100 times a minute by default (`THROTTLE_ANON`).
A busy storefront raises it.

## Where the code is

- `shop/models.py`: a product's price today (`current_price`, the sale
  window) and the parcel's rules.
- `shop/sellables.py`: how the shop sells through karni-commerce. The
  product adapter prices a line, refuses a product that is not for sale or
  sold out, and holds, takes and returns the stock. Change a rule here and
  every cart and checkout follows.
- `shop/services.py`, `shop/listeners.py`, `shop/events.py` and
  `shop/messages.py`: parcels (one per paid order, cancelled with its order),
  the signals `shipment_shipped`, `shipment_delivered` and
  `product_low_stock`, and the shop's emails.
- `shop/viewsets.py`: the price filters of the catalogue
  (`?min_price=`, `?max_price=`, `?ordering=effective_price`), what a shopper
  reads of a product, and `POST /api/shipments/<id>/ship/` and `deliver/`.
- `shop/models.py` also holds a variation's price and stock, and a review's
  rating rules (`Product.count_ratings`). `shop/services.py` says who may
  review (`review_problem`) and picks related products (`related`).
- `frontend/src/shop/VariationPicker.tsx`, `Reviews.tsx`, `Rating.tsx`,
  `WishlistButton.tsx` and `MoreProducts.tsx` (related and recently viewed):
  the product page's parts. `pages/wishlist.tsx` is the wishlist, and
  `pages/coupons.tsx`, `shipping.tsx` and `tax-rates.tsx` mount
  @karni/commerce-ui's pages.
- `shop/preferences.py`: the Shop tab of Settings (a Pydantic model: add a
  field with its default and it shows on the page). `shop/reports.py`: the
  shop's reports.
- `shop/dashboard.py`: the home tiles that need the server (running low, best
  sellers). The counts are karni.yaml's `dashboard:`.
- `shop/seeds.py`: the demo shop. Five categories with their children, 40
  products (some on sale, some sold out, one not for sale, seven sold in
  sizes or colours, two printable files), shipping zones in Europe, the
  United Kingdom, the United States and the rest of the world, a sales tax
  and a VAT rate, five coupons (one of them ended), and 26 orders placed
  through karni-commerce in every money and parcel state, some with a
  coupon, with their payments, refunds and invoices. The buyers whose
  parcels arrived reviewed them (10 reviews, karni.yaml's count), the demo
  customer keeps a wishlist, has one product left to review and bought both
  files, and three carts were left behind. Seeding sends no email.
- Digital products: `ProductFile` (a protected file, karni-storage) and
  `Download` in karni.yaml, `grant_downloads`, `download_link` and
  `take_download` in `shop/services.py`, `GET /api/downloads/get/<token>/`
  in `shop/viewsets.py`.
- `frontend/src/pages/settings.tsx`, `reports.tsx`, `abandoned-carts.tsx`,
  `order-invoice.tsx` and `order-packing-slip.tsx` mount the pages of
  @karni/ui and @karni/commerce-ui.
- `frontend/src/shop/`: the storefront (home, catalogue, product page,
  header and footer) and `ParcelPanel.tsx`, the parcel on the staff's order
  page. `frontend/src/pages/` holds a thin file per page: `cart.tsx`,
  `checkout.tsx`, `orders.tsx`, `order.tsx`, `order-new.tsx`,
  `customers.tsx` and `customer.tsx` mount `@karni/commerce-ui` (a customer's
  or the staff's version of each), `products.tsx` is the staff's catalogue,
  and `account.tsx` and `signin.tsx` mount `@karni/ui`.
- `shop/tests/`: the stock, price, parcel and email rules, the API for each
  role (a visitor, a customer, another customer, staff and a manager), the
  home tiles per role, refunds back into stock, orders placed by hand,
  backorders, query counts on the catalogue and the order lists, and the
  demo data.

The demo has one login per role, each with rows of its own: `staff@example.com`
works the orders and parcels, `manager@example.com` refunds, and
`customer@example.com` has orders in every state.

## What people usually change

| Change | In karni.yaml or the code |
|---|---|
| the product fields | `apps.shop.entities.Product.fields`, for example `weight: "decimal:6:2?"`, then `karni build`: the storefront keeps working |
| the payment provider and the currency | `modules.payments: {provider: razorpay, currency: inr}`, and `money:INR` on the product prices. Orders take the currency of the payments module |
| the parcel states | `apps.shop.entities.Shipment.fields.status` and the words in `frontend/src/` and `shop/sellables.py` |
| the terms version and url | `features.terms: {version: "2026-06", url: /terms, required: true}`, and the text in `frontend/src/shop/Terms.tsx` |
| how long checkout holds the stock | `modules.commerce: {hold_minutes: 60}` |
| the options products come in | `/attributes` in the app, or another field on `apps.shop.entities.Variation` in karni.yaml (`weight: "decimal:6:2?"`) |
| shipping zones, tax rates and coupons | `/shipping`, `/tax-rates` and `/coupons` in the app |
| prices that include tax | `modules.commerce: {prices_include_tax: true}` |
| the shop's name, address, sender and currency display | Settings, Details in the app |
| guest checkout, the terms, invoices, who gets new orders | Settings, Checkout |
| stock levels, sold out products, reviews, related products, downloads | Settings, Shop (their first values: `SHOP_LOW_STOCK`, `SHOP_REVIEWS_NEED_APPROVAL`, `SHOP_RELATED_COUNT`) |
| the text of an email | Settings, Emails |
| a setting the deployment fixes | `KARNI_PREFERENCES_LOCKED = {"commerce": {"guest_checkout": False}}` |
| where downloads are kept in production | `KARNI_STORAGE=s3` and the bucket's keys in `.env` (`modules.storage.provider`) |
| who may do what | `roles` in karni.yaml |
| what each role sees at home | `dashboard:` in karni.yaml (a tile counts an entity's rows, or places a code tile of `shop/dashboard.py` or karni-commerce by its key) |

## What it does not do

- Saved addresses in the account: the customers list is built from the
  orders (one customer per email). When the family's people records arrive
  it moves onto them, with the same screens.
- Shipping is priced by zone and method, not by weight.
- Recently viewed products are kept in the browser, not in the account.
- It sends no email to the people who left a cart, and no credit note for a
  refund.
- The settings are kept by karni-commerce until the family's preferences
  contract is installed: then they move onto it, with the same page. A logo
  and the change history of the settings come with it.

Out of scope for this recipe: a plugin or theme system, subscriptions,
several currencies at once (one currency per shop), live carrier rates,
several warehouses and a point of sale.
