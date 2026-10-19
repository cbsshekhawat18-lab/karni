#!/usr/bin/env bash
# Claim (b): every endpoint of the model-only viewset, via curl against 127.0.0.1:8521.
set -u
B=http://127.0.0.1:8521
J='Content-Type: application/json'
step() { echo; echo "### $1"; echo "\$ $2"; }
req() { curl -s -w '\n[HTTP %{http_code}]\n' "$@"; }

step "B1 unauthenticated list (read=Public)" "GET /api/venues/"
req $B/api/venues/

step "B2 unauthenticated create is refused (write=Authenticated)" "POST /api/venues/"
req -X POST $B/api/venues/ -H "$J" -d '{"name":"Anon","city":"X","capacity":1}'

step "B3 login (jwt mode)" "POST /api/auth/login/"
TOK=$(curl -s -X POST $B/api/auth/login/ -H "$J" -d '{"email":"alice@example.com","password":"x"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["access"])')
echo "access token: ${TOK:0:24}..."
A="Authorization: Bearer $TOK"

step "B4 create" "POST /api/venues/ (Bearer)"
C1=$(curl -s -X POST $B/api/venues/ -H "$J" -H "$A" -d '{"name":"Grand Hall","city":"Jaipur","capacity":300}')
echo "$C1"
ID=$(echo "$C1" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
curl -s -o /dev/null -w '[HTTP %{http_code}]\n' -X POST $B/api/venues/ -H "$J" -H "$A" -d '{"name":"Small Room","city":"Jaipur","capacity":20}'
curl -s -o /dev/null -w '[HTTP %{http_code}]\n' -X POST $B/api/venues/ -H "$J" -H "$A" -d '{"name":"Open Air","city":"Mumbai","capacity":5000}'

step "B5 validation error shape" "POST /api/venues/ with missing fields"
req -X POST $B/api/venues/ -H "$J" -H "$A" -d '{"name":"No capacity"}'

step "B6 retrieve" "GET /api/venues/$ID/"
req $B/api/venues/$ID/

step "B7 partial update" "PATCH /api/venues/$ID/"
req -X PATCH $B/api/venues/$ID/ -H "$J" -H "$A" -d '{"capacity":350}'

step "B8 full update" "PUT /api/venues/$ID/"
req -X PUT $B/api/venues/$ID/ -H "$J" -H "$A" -d '{"name":"Grand Hall (PUT)","city":"Jaipur","capacity":360}'

step "B9 read-only audit fields ignored on write" "PATCH created_by/id"
req -X PATCH $B/api/venues/$ID/ -H "$J" -H "$A" -d '{"id":"00000000-0000-0000-0000-000000000000","created_by":"00000000-0000-0000-0000-000000000000","capacity":361}'

step "B10 filtering exact / icontains / gte / lte" "GET ?city=Jaipur ; ?name__icontains=hall ; ?capacity__gte=300 ; ?capacity__lte=25"
for qs in 'city=Jaipur' 'name__icontains=hall' 'capacity__gte=300' 'capacity__lte=25' 'city=Nowhere'; do
  echo "?$qs -> $(curl -s "$B/api/venues/?$qs" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["count"], [r["name"] for r in d["results"]])')"
done
echo "unknown param ignored? ?bogus=1 -> $(curl -s "$B/api/venues/?bogus=1" | python3 -c 'import json,sys; print(json.load(sys.stdin)["count"])')"
echo "bad type ?capacity__gte=abc -> $(curl -s -w ' [HTTP %{http_code}]' "$B/api/venues/?capacity__gte=abc")"

step "B11 ordering" "GET ?ordering=capacity ; ?ordering=-capacity ; ?ordering=name"
for o in capacity -capacity name -created_at; do
  echo "?ordering=$o -> $(curl -s "$B/api/venues/?ordering=$o" | python3 -c 'import json,sys; d=json.load(sys.stdin); print([(r["name"], r["capacity"]) for r in d["results"]])')"
done
echo "default order (no param) -> $(curl -s "$B/api/venues/" | python3 -c 'import json,sys; d=json.load(sys.stdin); print([r["name"] for r in d["results"]])')"

step "B12 pagination" "GET ?page_size=2 ; ?page_size=2&page=2 ; ?page=99 ; ?page_size=1000"
req "$B/api/venues/?page_size=2"
req "$B/api/venues/?page_size=2&page=2"
req "$B/api/venues/?page=99"
echo "?page_size=1000 -> results: $(curl -s "$B/api/venues/?page_size=1000" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d["results"]), "of", d["count"])')"

step "B13 search WITHOUT search_fields declared" "GET ?search=Grand"
req "$B/api/venues/?search=Grand"
echo "OpenAPI list parameters for /api/venues/:"
curl -s $B/api/schema/ -H 'Accept: application/json' | python3 -c '
import json,sys
s=json.load(sys.stdin)
op=s["paths"]["/api/venues/"]["get"]
print(sorted(p["name"] for p in op.get("parameters",[])))'

step "B14 expand a relation on events" "GET /api/events/?expand=venue"
req "$B/api/events/?expand=venue&page_size=1"

step "B15 delete (soft) then 404" "DELETE /api/venues/$ID/ ; GET"
req -X DELETE $B/api/venues/$ID/ -H "$A"
req $B/api/venues/$ID/
echo "row in DB (deleted_at set)? -> $(psql -h 127.0.0.1 -p 5432 -At karni_audit_t2 -c "select name, deleted_at is not null from shop_venue where id='$ID'")"

step "B16 options / allowed methods" "OPTIONS /api/venues/"
curl -s -i -X OPTIONS $B/api/venues/ -H "$A" | grep -i '^Allow'

step "B17 schema: component, enum, vendor extensions" "GET /api/schema/"
curl -s $B/api/schema/ -H 'Accept: application/json' > /private/tmp/claude-501/-Users-chandrabhanshekhawat-Documents-www-Karni/005402c9-153c-4894-bbf4-1ab94a7068d3/scratchpad/audit/t2/b-schema.json
python3 - <<'PY'
import json
s=json.load(open("/private/tmp/claude-501/-Users-chandrabhanshekhawat-Documents-www-Karni/005402c9-153c-4894-bbf4-1ab94a7068d3/scratchpad/audit/t2/b-schema.json"))
print("openapi", s["openapi"], "| x-karni-auth-mode:", s.get("x-karni-auth-mode"))
print("paths:", [p for p in s["paths"] if p.startswith("/api/venues") or p.startswith("/api/events")])
g=s["paths"]["/api/venues/"]["get"]
print("GET /api/venues/: operationId", g["operationId"], "| x-karni-resource", g.get("x-karni-resource"), "| x-karni-access", g.get("x-karni-access"), "| security", g.get("security"))
print("  params:", [(p["name"], p["in"], p["schema"].get("type"), p["schema"].get("enum")) for p in g["parameters"]])
p=s["paths"]["/api/venues/"]["post"]
print("POST /api/venues/: x-karni-access", p.get("x-karni-access"), "| security", p.get("security"), "| requestBody schema", p["requestBody"]["content"]["application/json"]["schema"])
print("responses:", {k: v.get("content",{}).get("application/json",{}).get("schema") for k,v in g["responses"].items()})
comps=s["components"]["schemas"]
print("components:", sorted(k for k in comps if "Venue" in k or "Event" in k or "Status" in k))
print("Venue schema:", json.dumps(comps["Venue"], indent=1)[:1500])
print("Event.venue field:", comps["Event"]["properties"]["venue"])
print("Event.status field:", comps["Event"]["properties"]["status"])
for k in comps:
    if "Status" in k: print(k, comps[k])
print("Event required:", comps["Event"].get("required"))
print("VenueRequest schema:", comps.get("VenueRequest"))
print("deleted_at exposed anywhere?", any("deleted_at" in json.dumps(comps[k]) for k in comps if k.startswith(("Venue","Event"))))
PY
echo "DONE B"
