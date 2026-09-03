#!/usr/bin/env bash
# Muestra que elementos de Jetpack (compartir, me gusta, relacionados)
# esta renderizando la pagina del dashboard.

URL="https://digitalts.com.mx/monitoreo-gicsa/"
UA="Mozilla/5.0 (compatible; DTS-Monitor/1.0)"

tmp=$(mktemp)
curl -s -m 30 -A "$UA" "$URL" > "$tmp"

echo "bytes descargados: $(wc -c < "$tmp")"
echo
echo "=== ids y clases de Jetpack presentes ==="
grep -oE '(id|class)="[^"]*"' "$tmp" \
  | grep -iE 'sharedaddy|sd-sharing|sd-social|sd-like|sd-block|jp-post-flair|jp-relatedposts|sharing-hidden|likes-widget' \
  | sort -u

echo
echo "=== textos visibles ==="
for t in "Comparte esto" "Me gusta esto" "Personalizar botones" "Relacionado"; do
  n=$(grep -c "$t" "$tmp")
  echo "  '$t': $n"
done

echo
echo "=== el dashboard cargo? ==="
for t in "dts-monitor" "Monitoreo — GICSA" "Sincronizaci" ; do
  n=$(grep -c "$t" "$tmp")
  echo "  '$t': $n"
done

rm -f "$tmp"
