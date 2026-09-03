#!/usr/bin/env bash
# Detecta cuales de los sitios monitoreados corren WordPress y como
# responde su panel de administracion.

sitios=(
  "https://www.gicsa.com.mx"
  "https://www.laislamerida.mx"
  "https://www.laislaacapulco.com.mx"
  "https://www.explanadapuebla.com"
  "https://explanadapachuca.com"
  "https://explanadaculiacan.mx"
  "https://www.forumbuenavista.mx"
  "https://gocuernavaca.mx"
  "https://gorivieramaya.mx"
  "https://paseoarcosbosques.mx"
  "https://paseointerlomas.mx"
  "https://paseoqueretaro.mx"
)

UA="Mozilla/5.0 (compatible; DTS-Monitor/1.0)"

printf '%-32s %-10s %-10s %-10s %s\n' "SITIO" "PORTADA" "wp-login" "wp-json" "WORDPRESS?"
printf '%s\n' "--------------------------------------------------------------------------------"

for u in "${sitios[@]}"; do
  host=$(echo "$u" | sed -E 's#https?://##')

  portada=$(curl -s -o /dev/null -w '%{http_code}' -m 15 -L -A "$UA" "$u" 2>/dev/null)
  login=$(curl -s -o /dev/null -w '%{http_code}' -m 15 -L -A "$UA" "$u/wp-login.php" 2>/dev/null)
  api=$(curl -s -o /dev/null -w '%{http_code}' -m 15 -L -A "$UA" "$u/wp-json/" 2>/dev/null)

  # Rastros de WordPress en el HTML de la portada
  cuerpo=$(curl -s -m 15 -L -A "$UA" "$u" 2>/dev/null | head -c 200000)
  rastro="no"
  if echo "$cuerpo" | grep -qiE 'wp-content|wp-includes|/wp-json|generator" content="WordPress'; then
    rastro="si"
  fi

  veredicto="no"
  if [ "$rastro" = "si" ] || [ "$login" = "200" ] || [ "$api" = "200" ]; then
    veredicto="SI"
  fi

  printf '%-32s %-10s %-10s %-10s %s\n' "$host" "$portada" "$login" "$api" "$veredicto"
done
