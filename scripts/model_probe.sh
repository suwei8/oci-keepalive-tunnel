#!/usr/bin/env bash
# Kilo / OpenAI-compatible gateway latency probe.
#
# Runs on a remote host (fed over SSH stdin by the kilo-model-probe workflow)
# and prints exactly one CSV line to stdout:
#
#   name,model,target,tcp_ms,tls_ms,ttfb_ms,total_ms,http,ts
#
# Measurements
#   tcp_ms/tls_ms : network-only RTT to the Kilo edge (min of RUNS), via
#                   curl's time_connect / time_appconnect.
#   ttfb_ms       : time-to-first-byte through the opencode2api gateway using a
#                   streaming, max_tokens=1 request, so it captures
#                   network + queue + first-token time (NOT full generation).
#   total_ms      : full response time of the same request.
#
# Env: NAME, MODEL, TARGET, BASE_URL, API_KEY, RUNS (default 3), TIMEOUT (default 30)
set -uo pipefail

NAME="${NAME:-$(hostname)}"
MODEL="${MODEL:-beam-free}"
TARGET="${TARGET:-ai-gateway.kilo.ai}"
BASE_URL="${BASE_URL:-}"
API_KEY="${API_KEY:-}"
RUNS="${RUNS:-3}"
TIMEOUT="${TIMEOUT:-30}"

# minf A B -> smaller of A and B, treating empty as "no value yet"
minf() {
  awk -v a="$1" -v b="$2" 'BEGIN{
    if (b == "") { print a; exit }
    if (a == "") { print b; exit }
    print (b + 0 < a + 0) ? b : a
  }'
}

have_curl=0
command -v curl >/dev/null 2>&1 && have_curl=1

# --- 1) network RTT to the Kilo edge (TCP + TLS), min over RUNS ---
tcp="NA"; tls="NA"
if [ "$have_curl" -eq 1 ]; then
  best_tcp=""; best_tls=""
  i=1
  while [ "$i" -le "$RUNS" ]; do
    read -r c a <<<"$(curl -s -o /dev/null --max-time "$TIMEOUT" \
      -w '%{time_connect} %{time_appconnect}' "https://${TARGET}/" 2>/dev/null)"
    [ -n "${c:-}" ] && best_tcp="$(minf "$best_tcp" "$c")"
    [ -n "${a:-}" ] && best_tls="$(minf "$best_tls" "$a")"
    i=$((i + 1))
  done
  [ -n "$best_tcp" ] && tcp="$(awk "BEGIN{printf \"%.1f\", $best_tcp*1000}")"
  [ -n "$best_tls" ] && tls="$(awk "BEGIN{printf \"%.1f\", $best_tls*1000}")"
fi

# --- 2) first-token latency through the opencode2api gateway ---
# curl's time_starttransfer is unreliable behind Cloudflare/proxies: it reports
# the proxy's response headers (~20ms), not the model's first byte. So we time
# the first SSE "data:" line ourselves (first token) and the stream end.
ttfb="NA"; total="NA"; http="NA"
if [ "$have_curl" -eq 1 ] && [ -n "$BASE_URL" ] && [ -n "$API_KEY" ]; then
  best_ttfb=""; best_total=""
  i=1
  while [ "$i" -le "$RUNS" ]; do
    start_ns="$(date +%s%N)"
    first_ns=""; saw_data=0
    while IFS= read -r line; do
      case "$line" in
        data:*)
          if [ "$saw_data" -eq 0 ]; then
            first_ns="$(date +%s%N)"
            saw_data=1
          fi
          ;;
      esac
    done < <(curl -sN --max-time 60 \
      "${BASE_URL%/}/v1/chat/completions" \
      -H "Authorization: Bearer ${API_KEY}" \
      -H 'Content-Type: application/json' \
      -d "{\"model\":\"${MODEL}\",\"stream\":true,\"max_tokens\":1,\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}" 2>/dev/null)
    end_ns="$(date +%s%N)"
    if [ "$saw_data" -eq 1 ]; then
      best_ttfb="$(minf "$best_ttfb" "$(( (first_ns - start_ns) / 1000000 ))")"
      best_total="$(minf "$best_total" "$(( (end_ns - start_ns) / 1000000 ))")"
      http="200"
    fi
    i=$((i + 1))
  done
  [ -n "$best_ttfb" ] && ttfb="$best_ttfb"
  [ -n "$best_total" ] && total="$best_total"
fi

printf '%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
  "$NAME" "$MODEL" "$TARGET" "$tcp" "$tls" "$ttfb" "$total" "$http" \
  "$(date -u +%FT%TZ)"
