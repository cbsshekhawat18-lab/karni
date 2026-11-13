// /products: the catalogue for staff. Search, filters, sorting and paging, CSV export and
// import, and many products changed at once: select them, then set the price, the sale
// price, the stock or whether they are for sale. New and Edit show to the roles that may.
import { Page, ResourceTable } from "@karni/ui";
import { useNavigate } from "@tanstack/react-router";

export default function ProductsPage() {
  const navigate = useNavigate();
  return (
    <Page title="Products">
      <ResourceTable
        resource="products"
        bulkEdit={["price", "sale_price", "stock", "low_stock", "active", "featured"]}
        onRowClick={(row) =>
          void navigate({ to: "/shop/products/$id", params: { id: String(row.id) } })
        }
        onEdit={(row) =>
          void navigate({ to: "/shop/products/$id/edit", params: { id: String(row.id) } })
        }
        onCreate={() => void navigate({ to: "/shop/products/new" })}
      />
    </Page>
  );
}
