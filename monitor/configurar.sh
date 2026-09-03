#!/usr/bin/env bash
# Configura las credenciales de publicacion en digitalts.com.mx.
#
# La contrasena se teclea aqui y va directo al archivo .env: no pasa por
# el historial de la terminal ni queda en pantalla.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$DIR/.env"

echo
echo "  Configuracion de publicacion — digitalts.com.mx"
echo "  ==============================================="
echo
echo "  Antes de seguir necesitas un Application Password:"
echo "    1. Entra a https://digitalts.com.mx/wp-admin/profile.php"
echo "    2. Baja hasta 'Application Passwords'"
echo "    3. Nombre: DTS Monitor  ->  boton 'Add New'"
echo "    4. Copia la clave (se muestra UNA sola vez)"
echo

if [ -f "$ENV_FILE" ]; then
  echo "  Ya existe un .env. Se va a reemplazar."
  read -r -p "  Continuar? [s/N] " ok
  [[ "$ok" =~ ^[sSyY]$ ]] || { echo "  Cancelado."; exit 0; }
  echo
fi

read -r -p "  Usuario de WordPress: " WP_USER
[ -n "$WP_USER" ] || { echo "  El usuario no puede ir vacio."; exit 1; }

# -s oculta lo que se teclea.
read -r -s -p "  Application Password: " WP_PASS
echo
[ -n "$WP_PASS" ] || { echo "  La clave no puede ir vacia."; exit 1; }

umask 077
cat > "$ENV_FILE" <<EOF
WP_USER=$WP_USER
WP_APP_PASSWORD=$WP_PASS
EOF
chmod 600 "$ENV_FILE"

echo
echo "  Guardado en $ENV_FILE (permisos 600, ignorado por git)"
echo
echo "  Probando la conexion..."
echo

VENV="$HOME/dts-venv/bin/python"
PY="${VENV:-python3}"
[ -x "$PY" ] || PY="python3"

cd "$DIR"
if [ ! -f dashboard-publico.html ]; then
  echo "  No hay dashboard todavia, generandolo..."
  "$PY" monitor.py --dashboard >/dev/null
fi

rm -f .ultima-publicacion
if "$PY" publicar.py; then
  echo
  echo "  Listo. La pagina ya esta publicada:"
  echo "  https://digitalts.com.mx/monitoreo-gicsa"
  echo
  echo "  De aqui en adelante se actualiza sola:"
  echo "    * de inmediato cuando un sitio cambia de estado"
  echo "    * cada 5 minutos como latido"
else
  echo
  echo "  Fallo la publicacion. Revisa que el usuario y la clave sean"
  echo "  correctos y vuelve a correr este script."
  exit 1
fi
