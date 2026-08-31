#!/usr/bin/env bash
# Diagnostico profundo de un dominio: compara www vs apex, https vs http,
# repite para descartar fallas transitorias.

for base in "$@"; do
  echo "############################################################"
  echo "# $base"
  echo "############################################################"
  for h in "www.$base" "$base"; do
    echo
    echo "--- $h ---"
    ips=$(getent hosts "$h" | awk '{print $1}' | sort -u | tr '\n' ' ')
    if [ -z "$ips" ]; then
      echo "  DNS: NO RESUELVE"
      continue
    fi
    echo "  DNS: $ips"

    for proto in https http; do
      for i in 1 2 3; do
        out=$(curl -s -o /dev/null \
          -w "HTTP %{http_code} | %{time_total}s | final: %{url_effective}" \
          -m 20 -L -A "Mozilla/5.0 (compatible; DTS-Monitor/1.0)" \
          "$proto://$h" 2>&1)
        echo "  $proto intento $i: $out"
      done
    done

    echo "  --- cabeceras (https) ---"
    curl -s -I -m 20 -A "Mozilla/5.0 (compatible; DTS-Monitor/1.0)" \
      "https://$h" 2>&1 | head -12 | sed 's/^/    /'
  done
  echo
done
