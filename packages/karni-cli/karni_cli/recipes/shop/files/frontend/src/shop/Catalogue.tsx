// The catalogue: every product for sale as cards, with search, a category (and its
// children), a price range, the sort order and pages, all kept in the address.
import {
  Input,
  Label,
  ResourceGrid,
  Select,
  useResourceList,
  usePageMeta,
} from "@karni/ui";
import { useId } from "react";
import { ProductCard } from "./ProductCard";
import { useSearchValues, useSetSearch } from "./search";
import { useShopName } from "./name";
import type { Category, Product } from "./types";

const SORTS = [
  { value: "name", label: "Name" },
  { value: "-created_at", label: "Newest" },
  { value: "effective_price", label: "Price, low to high" },
  { value: "-effective_price", label: "Price, high to low" },
];

function useCategoryOptions() {
  const all =
    useResourceList<Category>("categories", { pageSize: 100 }).data?.results ??
    [];
  const tops = all.filter((category) => category.parent === null);
  return tops.flatMap((top) => [
    { value: top.id, label: top.name },
    ...all
      .filter((child) => child.parent === top.id)
      .map((child) => ({
        value: child.id,
        label: `${top.name}: ${child.name}`,
      })),
  ]);
}

export function Catalogue() {
  const shopName = useShopName();
  const values = useSearchValues();
  const setSearch = useSetSearch();
  const options = useCategoryOptions();
  const ids = { category: useId(), min: useId(), max: useId() };
  const chosen = options.find((option) => option.value === values.category);
  usePageMeta({
    title: chosen ? `${chosen.label} | Products` : "Products",
    siteName: shopName,
    description: `Everything ${shopName} sells${chosen ? ` in ${chosen.label}` : ""}.`,
  });
  const filters = {
    ...(values.category
      ? { categories: values.category, categories_descendants: true }
      : {}),
    ...(values.min ? { min_price: values.min } : {}),
    ...(values.max ? { max_price: values.max } : {}),
  };
  const price = (key: "min" | "max", label: string) => (
    <div className="flex flex-col gap-1 sm:w-28">
      <Label htmlFor={ids[key]}>{label}</Label>
      <Input
        id={ids[key]}
        type="number"
        min={0}
        inputMode="decimal"
        defaultValue={values[key] ?? ""}
        onBlur={(event) => setSearch({ [key]: event.target.value, page: "" })}
        onKeyDown={(event) => {
          if (event.key === "Enter")
            setSearch({ [key]: event.currentTarget.value, page: "" });
        }}
      />
    </div>
  );
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{chosen?.label ?? "Products"}</h1>
      <ResourceGrid<Product>
        resource="products"
        label="Products"
        searchLabel="Search the shop"
        sortOptions={SORTS}
        filters={filters}
        search={values.q ?? ""}
        onSearchChange={(q) => setSearch({ q, page: "" })}
        ordering={values.sort ?? "name"}
        onOrderingChange={(sort) => setSearch({ sort, page: "" })}
        page={Number(values.page ?? "1") || 1}
        onPageChange={(page) => setSearch({ page: String(page) })}
        renderCard={(product) => <ProductCard product={product} />}
        toolbar={
          <>
            <div className="flex flex-col gap-1 sm:w-60">
              <Label id={ids.category}>Category</Label>
              <Select
                aria-labelledby={ids.category}
                value={values.category ?? null}
                options={options}
                clearable
                clearLabel="All categories"
                placeholder="All categories"
                onValueChange={(category) =>
                  setSearch({ category: category ?? "", page: "" })
                }
              />
            </div>
            {price("min", "From")}
            {price("max", "To")}
          </>
        }
      />
    </div>
  );
}
