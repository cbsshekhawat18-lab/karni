#!/usr/bin/env bash
# Tier-5 audit: time from `karni new` to a running, seeded app (no Docker).
# Mirrors docs/quickstart.md (host venv active, cp .env.example .env, MEDIA/STATIC
# appended) and examples/eventhub/scripts/e2e.sh (Django + Celery worker, poll
# /health/ready/). Ports 8551 (Django) / 8552 (Vite) only.
set -u
S=<REDACTED>/audit/t5
K=<REDACTED>
export VIRTUAL_ENV=$S/qsvenv
export PATH=$S/qsvenv/bin:$PATH
export KARNI_UI_SRC=$K/packages/karni-ui
export DATABASE_URL=postgres://localhost/karni_audit_t5
export REDIS_URL=redis://127.0.0.1:6379/9
export KARNI_FRONTEND_URL=http://127.0.0.1:8552
export KARNI_API_PROXY=http://127.0.0.1:8551
OUT=$S/timing
LOG=$S/timing-steps.tsv
rm -rf "$OUT"; mkdir -p "$OUT"
printf 'step\tstart_epoch\tend_epoch\tseconds\texit\n' > "$LOG"
now() { date +%s.%N; }
record() { # name start end exit
  printf '%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$(echo "$3 - $2" | bc)" "$4" >> "$LOG"
}

echo "== machine: $(sysctl -n machdep.cpu.brand_string), RAM $(sysctl -n hw.memsize) bytes, node $(node --version), npm $(npm --version), python $(python --version 2>&1)"
echo "== which karni: $(command -v karni)"

# pre-step: database (environment, not part of the quickstart window)
s=$(now); dropdb -h 127.0.0.1 -p 5432 --if-exists karni_audit_t5 && createdb -h 127.0.0.1 -p 5432 karni_audit_t5; rc=$?; e=$(now); record "pre:createdb" "$s" "$e" "$rc"

T_START=$(now)
# 1. karni new
cd "$OUT"
s=$(now); karni new timing_app -o "$OUT" > "$S/step1-karni-new.log" 2>&1; rc=$?; e=$(now); record "1:karni_new" "$s" "$e" "$rc"
cat "$S/step1-karni-new.log"
cd "$OUT/timing_app" || { echo "no project dir"; exit 1; }

# 2. .env as the quickstart does (exported vars above win over .env)
s=$(now); cp .env.example .env && printf 'MEDIA_ROOT=data/media\nSTATIC_ROOT=data/static\n' >> .env; rc=$?; e=$(now); record "2:env" "$s" "$e" "$rc"

# 3. frontend deps
s=$(now); (cd frontend && npm install > "$S/step3-npm-install.log" 2>&1); rc=$?; e=$(now); record "3:npm_install" "$s" "$e" "$rc"
tail -5 "$S/step3-npm-install.log"

# 4. migrate
s=$(now); karni migrate > "$S/step4-migrate.log" 2>&1; rc=$?; e=$(now); record "4:karni_migrate" "$s" "$e" "$rc"
tail -3 "$S/step4-migrate.log"

# 5. seed
s=$(now); karni seed > "$S/step5-seed.log" 2>&1; rc=$?; e=$(now); record "5:karni_seed" "$s" "$e" "$rc"
cat "$S/step5-seed.log"

# 6. start the stack: Django :8551, Celery worker, Vite :8552; poll readiness
s=$(now)
nohup karni serve --local --port 8551 > "$S/django-8551.log" 2>&1 &
echo $! > "$S/django.pid"
nohup karni worker > "$S/worker.log" 2>&1 &
echo $! > "$S/worker.pid"
(cd frontend && nohup npm run dev -- --port 8552 --strictPort --host 127.0.0.1 > "$S/vite-8552.log" 2>&1 & echo $! > "$S/vite.pid")
ready=""; vite=""
for i in $(seq 1 240); do
  if [ -z "$ready" ]; then
    code=$(curl -s -o "$S/health-ready-body.json" -w '%{http_code}' http://127.0.0.1:8551/health/ready/ 2>/dev/null)
    if [ "$code" = "200" ]; then ready=$(now); record "6a:health_ready_200" "$s" "$ready" 0; fi
  fi
  if [ -z "$vite" ]; then
    vcode=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8552/ 2>/dev/null)
    if [ "$vcode" = "200" ]; then vite=$(now); record "6b:vite_200" "$s" "$vite" 0; fi
  fi
  if [ -n "$ready" ] && [ -n "$vite" ]; then break; fi
  sleep 0.5
done
[ -z "$ready" ] && record "6a:health_ready_200" "$s" "$(now)" "TIMEOUT"
[ -z "$vite" ] && record "6b:vite_200" "$s" "$(now)" "TIMEOUT"
T_END=$(now)
record "TOTAL(karni_new..health_ready_200)" "$T_START" "${ready:-$T_END}" 0
record "TOTAL(karni_new..both_200)" "$T_START" "$T_END" 0
echo "== health body:"; cat "$S/health-ready-body.json"; echo
echo "== health last code: $code ; vite last code: $vcode"
echo "== steps:"; cat "$LOG"
