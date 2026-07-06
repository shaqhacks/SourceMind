#!/usr/bin/env bash
# Live backend E2E smoke for SourceMind v2 (no LLM key on purpose —
# generation/chat must degrade cleanly). Prints PASS/FAIL per step.
set -u
cd "$(dirname "$0")/../backend"
SCRATCH="$(mktemp -d /tmp/smv2-smoke.XXXXXX)"
DATA="$SCRATCH/smoke-data"
rm -rf "$DATA"; mkdir -p "$DATA"
PORT=8077
BASE="http://127.0.0.1:$PORT"
FAILS=0
CHECKS=0

step() { CHECKS=$((CHECKS+1)); if [ "$2" = "1" ]; then echo "PASS: $1"; else echo "FAIL: $1 -- $3"; FAILS=$((FAILS+1)); fi; }

SMV2_DATA_DIR="$DATA" SMV2_BACKUPS_ENABLED=1 uv run uvicorn app.main:app --port $PORT --log-level warning &
SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT

# 1. health up
ok=0
for i in $(seq 1 40); do
  if curl -sf "$BASE/health" | grep -q '"ok"'; then ok=1; break; fi
  sleep 0.5
done
step "health endpoint up" $ok "server never became healthy"
[ $ok = 1 ] || { echo "ABORT"; exit 1; }

# 2. sample course seeded on first run
sleep 1
COURSES=$(curl -s "$BASE/api/courses")
echo "$COURSES" | grep -q "Welcome to SourceMind"; step "sample course auto-seeded" $((1-$?)) "$COURSES"
SAMPLE_ID=$(echo "$COURSES" | uv run python -c "import sys,json;print(json.load(sys.stdin)[0]['id'])" 2>/dev/null)

# 3. sample ingest completes via real worker
ok=0
for i in $(seq 1 60); do
  ST=$(curl -s "$BASE/api/courses/$SAMPLE_ID" | uv run python -c "import sys,json;print(json.load(sys.stdin).get('status',''))" 2>/dev/null)
  if [ "$ST" = "ready" ]; then ok=1; break; fi
  sleep 0.5
done
step "sample ingest reached ready (worker ran)" $ok "last status: $ST"
SECS=$(curl -s "$BASE/api/courses/$SAMPLE_ID/sections")
NSEC=$(echo "$SECS" | uv run python -c "import sys,json;print(len(json.load(sys.stdin)))" 2>/dev/null)
[ "$NSEC" = "3" ]; step "sample outline = 3 bookmark chapters" $((1-$?)) "got $NSEC"

# 4. real upload flow: new course + fixture PDF + ingest
CID=$(curl -s -X POST "$BASE/api/courses" -H 'content-type: application/json' -d '{"title":"Smoke Course"}' | uv run python -c "import sys,json;print(json.load(sys.stdin)['id'])")
UP=$(curl -s -o /dev/null -w "%{http_code}" -F "file=@tests/fixtures/pdfs/with_bookmarks.pdf;type=application/pdf" "$BASE/api/courses/$CID/assets")
[ "$UP" = "201" ] || [ "$UP" = "200" ]; step "PDF upload accepted ($UP)" $((1-$?)) "code $UP"
BAD=$(curl -s -o /dev/null -w "%{http_code}" -F "file=@scripts/make_sample.py;type=application/pdf" "$BASE/api/courses/$CID/assets")
[ "$BAD" = "415" ]; step "non-PDF rejected 415" $((1-$?)) "code $BAD"
JOB=$(curl -s -X POST "$BASE/api/courses/$CID/ingest" | uv run python -c "import sys,json;print(json.load(sys.stdin)['job_id'])" 2>/dev/null)

# 5. SSE stream on the ingest job reaches terminal
SSE=$(curl -sN --max-time 30 "$BASE/api/jobs/$JOB/events" | head -40)
echo "$SSE" | grep -q "succeeded"; step "SSE job stream emitted terminal succeeded" $((1-$?)) "$(echo "$SSE" | tail -3)"

# 6. reader endpoints
SEC1=$(curl -s "$BASE/api/courses/$CID/sections" | uv run python -c "import sys,json;print(json.load(sys.stdin)[0]['id'])")
BODY=$(curl -s "$BASE/api/sections/$SEC1" | uv run python -c "import sys,json;d=json.load(sys.stdin);print(len(d['body_md']))")
[ "$BODY" -gt 100 ] 2>/dev/null; step "section body_md extracted (${BODY} chars)" $((1-$?)) "len=$BODY"
PR=$(curl -s -o /dev/null -w "%{http_code}" -X PUT "$BASE/api/courses/$CID/progress" -H 'content-type: application/json' -d "{\"section_id\":\"$SEC1\",\"scroll_pos\":0.42}")
[ "$PR" = "200" ]; step "progress saved" $((1-$?)) "code $PR"
RES=$(curl -s "$BASE/api/courses/$CID/progress" | uv run python -c "import sys,json;print(json.load(sys.stdin)['scroll_pos'])")
[ "$RES" = "0.42" ]; step "progress resumes (scroll_pos=$RES)" $((1-$?)) "got $RES"

# 7. export zip
XZ=$(curl -s -o "$SCRATCH/export.zip" -w "%{http_code}" "$BASE/api/courses/$CID/export")
SZ=$(stat -f%z "$SCRATCH/export.zip" 2>/dev/null || echo 0)
[ "$XZ" = "200" ] && [ "$SZ" -gt 1000 ] && unzip -t "$SCRATCH/export.zip" >/dev/null 2>&1; step "export zip valid ($SZ bytes)" $((1-$?)) "code=$XZ size=$SZ"

# 8. review surfaces (empty but shaped)
RQ=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/courses/$CID/review/queue")
RS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/review/summary")
[ "$RQ" = "200" ] && [ "$RS" = "200" ]; step "review queue+summary 200" $((1-$?)) "queue=$RQ summary=$RS"

# 9. LLM-dependent paths degrade cleanly without a provider (no key configured)
LJ=$(curl -s -X POST "$BASE/api/sections/$SEC1/lesson" | uv run python -c "import sys,json;print(json.load(sys.stdin)['job_id'])" 2>/dev/null)
ok=0
for i in $(seq 1 30); do
  JST=$(curl -s "$BASE/api/jobs/$LJ" | uv run python -c "import sys,json;print(json.load(sys.stdin)['status'])" 2>/dev/null)
  if [ "$JST" = "failed" ]; then ok=1; break; fi
  [ "$JST" = "succeeded" ] && break
  sleep 0.5
done
step "lesson job without provider fails cleanly (no wedge)" $ok "status: $JST"
LST=$(curl -s "$BASE/api/sections/$SEC1" | uv run python -c "import sys,json;print(json.load(sys.stdin)['lesson_status'])")
[ "$LST" = "failed" ]; step "lesson_status=failed (retryable, not stuck)" $((1-$?)) "got $LST"
CH=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/courses/$CID/chat" -H 'content-type: application/json' -d '{"message":"what is this book about?"}' --max-time 20)
case "$CH" in 4*|5*) ok=1;; *) ok=0;; esac
step "chat without provider returns clean HTTP error ($CH), no hang" $ok "code $CH"

# 10. estimates + usage still work with empty ledger
ES=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/sections/$SEC1/lesson/estimate")
US=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/llm/usage")
[ "$ES" = "200" ] && [ "$US" = "200" ]; step "estimate + usage 200 with no history" $((1-$?)) "est=$ES usage=$US"

# 11. backup ran on startup (SMV2_BACKUPS_ENABLED=1)
sleep 1
NB=$(ls "$DATA/backups" 2>/dev/null | wc -l | tr -d ' ')
[ "$NB" -ge 1 ]; step "startup backup created ($NB file)" $((1-$?)) "backups dir: $(ls "$DATA/backups" 2>/dev/null)"

# 12. restart durability: kill + restart, no rewedge, data intact
kill $SRV; wait $SRV 2>/dev/null
SMV2_DATA_DIR="$DATA" uv run uvicorn app.main:app --port $PORT --log-level warning &
SRV=$!
ok=0
for i in $(seq 1 40); do
  if curl -sf "$BASE/health" >/dev/null; then ok=1; break; fi
  sleep 0.5
done
step "restart: healthy again" $ok "no health after restart"
N2=$(curl -s "$BASE/api/courses" | uv run python -c "import sys,json;print(len(json.load(sys.stdin)))")
[ "$N2" = "2" ]; step "restart: both courses survive (no re-seed, no loss)" $((1-$?)) "got $N2 courses"

echo "===================="
echo "SMOKE RESULT: $FAILS failures across $CHECKS checks"
exit $FAILS
