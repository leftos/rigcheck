#!/usr/bin/env bash
# Run rigcheck against every git repo under D:/ with a commit in the last 30 days, plus $HOME,
# from the current checkout (a worktree or main). Writes .tmp/smoke/<name>.json and prints
# counts only: findings per rule summed over all targets, then each target's nonzero rules.
# Usage: bash .claude/skills/rigcheck-nextup/smoke.sh [days]
set -u
days="${1:-30}"
out=.tmp/smoke
mkdir -p "$out"
since=$(date -d "-$days days" +%Y-%m-%d)
targets=()
for dir in /d/*/; do
  dir="${dir%/}"
  [ "$(basename "$dir")" = rigcheck ] && continue
  [ -e "$dir/.git" ] || continue
  last=$(git -C "$dir" log -1 --format=%cs 2>/dev/null) || continue
  [[ "$last" > "$since" || "$last" == "$since" ]] && targets+=("$dir")
done
failed=0
run() {
  local name="$1" target="$2"
  uv run rigcheck check "$target" --format json > "$out/$name.json" 2> "$out/$name.err"
  if ! jq -e . "$out/$name.json" > /dev/null 2>&1; then
    echo "FAILED $name (see $out/$name.err)"
    failed=1
  fi
}
for dir in "${targets[@]}"; do run "$(basename "$dir")" "$dir"; done
run home "$HOME"
echo "targets: ${#targets[@]} repos since $since, plus home"
echo "== findings per rule and layer (repo layer summed over repos; user and plugin layers from the home run)"
{
  for file in "$out"/*.json; do
    [ "$(basename "$file")" = home.json ] && continue
    jq -r '.findings[]? | select(.layer == "repo" or .layer == "memory") | "\(.rule)\t\(.layer)"' "$file"
  done
  jq -r '.findings[]? | select(.layer != "repo" and .layer != "memory") | "\(.rule)\t\(.layer)"' "$out/home.json"
} | sort | uniq -c | sort -rn
echo "== repo-layer findings per repo"
for file in "$out"/*.json; do
  [ "$(basename "$file")" = home.json ] && continue
  jq -r --arg n "$(basename "$file" .json)" \
    '[.findings[]? | select(.layer == "repo" or .layer == "memory") | .rule] | group_by(.) | map("\(.[0])=\(length)")
     | select(length > 0) | "\($n): \(join(" "))"' "$file" 2> /dev/null
done
internal=$(jq -rs '[.[].findings[]? | select(.rule == "internal-error")] | length' "$out"/*.json)
echo "internal-error: $internal"
[ "$failed" = 0 ] && [ "$internal" = 0 ]
