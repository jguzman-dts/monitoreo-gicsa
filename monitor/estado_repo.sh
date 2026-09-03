#!/usr/bin/env bash
# Consulta el estado del repositorio en GitHub y si Actions ve el workflow.
REPO="jguzman-dts/monitoreo-gicsa"
API="https://api.github.com/repos/$REPO"

echo "=== REPOSITORIO ==="
r=$(curl -s -m 20 "$API")
if echo "$r" | grep -q '"message": *"Not Found"'; then
  echo "  NO ENCONTRADO o es PRIVADO (la API publica no lo ve)"
else
  for k in name private visibility default_branch pushed_at; do
    v=$(echo "$r" | grep -o "\"$k\": *[^,]*" | head -1 | cut -d: -f2- | tr -d ' "')
    printf '  %-16s %s\n' "$k" "$v"
  done
fi

echo
echo "=== WORKFLOWS QUE ACTIONS DETECTA ==="
w=$(curl -s -m 20 "$API/actions/workflows")
if echo "$w" | grep -q '"message"'; then
  echo "  $(echo "$w" | grep -o '"message": *"[^"]*"' | cut -d'"' -f4)"
else
  echo "  total: $(echo "$w" | grep -o '"total_count": *[0-9]*' | grep -o '[0-9]*')"
  echo "$w" | grep -o '"name": *"[^"]*"' | cut -d'"' -f4 | sed 's/^/    - /'
  echo "  estado:"
  echo "$w" | grep -o '"state": *"[^"]*"' | cut -d'"' -f4 | sed 's/^/    /'
fi

echo
echo "=== ARCHIVO EN LA RAMA POR DEFECTO ==="
f=$(curl -s -m 20 "$API/contents/.github/workflows/monitor.yml")
if echo "$f" | grep -q '"message"'; then
  echo "  $(echo "$f" | grep -o '"message": *"[^"]*"' | cut -d'"' -f4)"
else
  echo "  presente, $(echo "$f" | grep -o '"size": *[0-9]*' | grep -o '[0-9]*') bytes"
fi
