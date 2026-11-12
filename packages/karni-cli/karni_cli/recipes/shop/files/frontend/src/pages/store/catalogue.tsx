// /shop: the catalogue (store/Catalogue.tsx).
import { Catalogue } from "../../store/Catalogue";

export default function CataloguePage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Shop</h1>
      <Catalogue />
    </div>
  );
}
