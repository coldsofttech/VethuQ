#!/usr/bin/env bash
# Smoke-tests one built image the way a runner uses it (github/README.md):
#
#   smoke.sh IMAGE FIXTURES_DIR WORK_DIR
#
# 1. With no models in the cache, a job is refused with a sealed result that says so.
# 2. `fetch-models` fills the cache: the one step with a network, given no key and no payload.
# 3. The synthetic job is read with NO network against the cache.
# 4. A model file that no longer matches the lock makes the job refuse, and read nothing.
set -euo pipefail

image="$1"
fixtures="$2"
work="$3"
key=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8
job=fixture-job-0001

rm -rf "$work"
mkdir -p "$work/models" "$work/empty" "$work/out"
chmod 0777 "$work/models" "$work/empty" "$work/out"

harden=(--rm --cap-drop ALL --security-opt no-new-privileges --user "$(id -u):$(id -g)" --tmpfs /tmp)

run_job() {  # run_job MODELS_DIR -> the job's exit code
    docker run "${harden[@]}" --network none -e VETHUQ_MASTER_KEY="$key" \
        -v "$fixtures/payload:/payload:ro" -v "$work/out:/out" -v "$1:/opt/vethuq/models:ro" \
        "$image" run --job-id "$job" --payload /payload --out /out
}

result() {  # result EXPRESSION: evaluate it against the sealed result `r`
    docker run --rm --network none --entrypoint python -e VETHUQ_MASTER_KEY="$key" \
        -v "$work/out:/out:ro" "$image" -c "
import os
from vethuq_worker import ResultReader
r = ResultReader(os.environ['VETHUQ_MASTER_KEY']).read('$job', open('/out/result.bin', 'rb').read())
assert $1, (r.status, r.error_code)
"
}

echo "== 1. no models: the job is refused, and says why"
code=0
run_job "$work/empty" || code=$?
[ "$code" -eq 1 ] || { echo "expected exit 1, got $code"; exit 1; }
result "r.status == 'failed' and r.error_code == 'models_missing'"

echo "== 2. fetch the models (network, no key, no payload)"
docker run "${harden[@]}" -v "$work/models:/opt/vethuq/models" "$image" fetch-models

echo "== 3. read the synthetic job with no network"
rm -f "$work/out/result.bin"
run_job "$work/models"
test -s "$work/out/result.bin"
result "r.status == 'done' and len(r.pages) == 2"

echo "== 4. a model that no longer matches the lock is refused"
victim="$(find "$work/models" -type f | head -n 1)"
printf 'x' >> "$victim"
rm -f "$work/out/result.bin"
code=0
run_job "$work/models" || code=$?
[ "$code" -eq 1 ] || { echo "expected exit 1 for a changed model, got $code"; exit 1; }
result "r.status == 'failed' and r.error_code == 'models_unverified'"

echo "smoke test ok: $image"
