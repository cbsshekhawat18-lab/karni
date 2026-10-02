import { useEffect, useState } from "react";
import { Page } from "@karni/ui";
import { Button } from "@karni/ui/dist/button";
import axios from "axios";

// Known-bad page for `karni rules --check` (K201, K202, K203, K204, K005).
export function InvoicesPage() {
  const [rows, setRows] = useState<string[]>([]);
  useEffect(() => {
    void fetch("/api/invoices/").then((r) => r.json()).then(setRows);
  }, []);
  // eslint-disable-next-line karni/no-raw-elements
  const socket = new WebSocket("ws://localhost");
  void axios;
  void socket;
  return (
    <Page title="Invoices">
      <table>
        <tbody>
          {rows.map((row) => (
            <tr key={row}>
              <td>{row}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <form>
        <input name="q" />
      </form>
      <Button>Add</Button>
    </Page>
  );
}
// padding line 0 to exceed the 50-line page cap
// padding line 1 to exceed the 50-line page cap
// padding line 2 to exceed the 50-line page cap
// padding line 3 to exceed the 50-line page cap
// padding line 4 to exceed the 50-line page cap
// padding line 5 to exceed the 50-line page cap
// padding line 6 to exceed the 50-line page cap
// padding line 7 to exceed the 50-line page cap
// padding line 8 to exceed the 50-line page cap
// padding line 9 to exceed the 50-line page cap
// padding line 10 to exceed the 50-line page cap
// padding line 11 to exceed the 50-line page cap
// padding line 12 to exceed the 50-line page cap
// padding line 13 to exceed the 50-line page cap
// padding line 14 to exceed the 50-line page cap
// padding line 15 to exceed the 50-line page cap
// padding line 16 to exceed the 50-line page cap
// padding line 17 to exceed the 50-line page cap
// padding line 18 to exceed the 50-line page cap
// padding line 19 to exceed the 50-line page cap
// padding line 20 to exceed the 50-line page cap
// padding line 21 to exceed the 50-line page cap
// padding line 22 to exceed the 50-line page cap
// padding line 23 to exceed the 50-line page cap
// padding line 24 to exceed the 50-line page cap
