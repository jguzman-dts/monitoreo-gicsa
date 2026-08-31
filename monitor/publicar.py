#!/usr/bin/env python3
"""
Publica el dashboard publico en digitalts.com.mx.

Actualiza una pagina de WordPress vIa la API REST usando un Application
Password. Las credenciales NUNCA viven en este archivo: se leen de `.env`,
que esta en .gitignore.

Politica de publicacion
-----------------------
El monitor corre cada minuto, pero NO publica cada minuto: 1,440 escrituras
diarias contra WordPress es abuso de la API y termina en bloqueo. En su lugar:

  * Publica SIEMPRE que cambie el estado de algun sitio (una caida se
    refleja en el sitio publico en menos de un minuto).
  * Fuera de eso, publica un "latido" cada PUBLICAR_CADA_MIN para que la
    marca de tiempo no envejezca.

Asi lo urgente es inmediato y lo rutinario es barato.
"""

import os
import sys
import json
import base64
import datetime
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Falta requests.")

BASE = Path(__file__).resolve().parent
ENV = BASE / ".env"
MARCA = BASE / ".ultima-publicacion"

SITIO = "https://digitalts.com.mx"
SLUG = "monitoreo-gicsa"
PAGE_ID = 3880  # digitalts.com.mx/monitoreo-gicsa
TITULO = "Monitoreo de disponibilidad — GICSA"
PUBLICAR_CADA_MIN = 5


def cargar_env():
    """Lee .env sin dependencias. Devuelve dict."""
    datos = {}
    if ENV.exists():
        for linea in ENV.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            k, _, v = linea.partition("=")
            datos[k.strip()] = v.strip().strip('"').strip("'")
    # Las variables de entorno ganan sobre el archivo
    for k in ("WP_USER", "WP_APP_PASSWORD", "WP_PAGE_ID"):
        if os.environ.get(k):
            datos[k] = os.environ[k]
    return datos


def cabeceras(env):
    usuario = env.get("WP_USER")
    clave = env.get("WP_APP_PASSWORD")
    if not usuario or not clave:
        raise RuntimeError(
            "Faltan credenciales. Crea el archivo:\n"
            f"  {ENV}\n"
            "con estas dos lineas:\n"
            "  WP_USER=tu-usuario-de-wordpress\n"
            "  WP_APP_PASSWORD=xxxx xxxx xxxx xxxx xxxx xxxx\n\n"
            "El Application Password se genera en:\n"
            "  https://digitalts.com.mx/wp-admin/profile.php\n"
            "  seccion 'Application Passwords'."
        )
    token = base64.b64encode(f"{usuario}:{clave}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json",
        "User-Agent": "DTS-Monitor/1.0",
    }


def toca_publicar(hubo_cambios):
    if hubo_cambios:
        return True, "cambio de estado"
    if not MARCA.exists():
        return True, "primera publicacion"
    try:
        ultima = datetime.datetime.fromisoformat(
            MARCA.read_text(encoding="utf-8").strip()
        )
    except ValueError:
        return True, "marca ilegible"
    minutos = (datetime.datetime.now() - ultima).total_seconds() / 60
    if minutos >= PUBLICAR_CADA_MIN:
        return True, f"latido ({int(minutos)} min)"
    return False, f"sin cambios, ultima hace {int(minutos)} min"


RAIZ = "dts-monitor"


def envolver(html_completo):
    """
    Convierte la pagina suelta en un bloque insertable en WordPress.

    Los estilos del dashboard definen `:root` y `body`, que en una pagina
    suelta son correctos pero dentro de WordPress pisarian el tema del sitio.
    Aqui se reescriben para vivir bajo `.dts-monitor`, de modo que el bloque
    quede aislado y no afecte nada mas de digitalts.com.mx.
    """
    import re
    estilo = re.search(r"<style>(.*?)</style>", html_completo, re.S)
    cuerpo = re.search(r"<body>(.*?)</body>", html_completo, re.S)
    script = re.search(r"<script>(.*?)</script>", html_completo, re.S)

    partes = ["<!-- wp:html -->"]

    if estilo:
        css = estilo.group(1)
        # Las variables y el reset dejan de ser globales.
        css = css.replace(':root:not([data-theme="light"])',
                          f'.{RAIZ}:not([data-theme="light"])')
        css = css.replace(':root[data-theme="dark"]', f'.{RAIZ}[data-theme="dark"]')
        css = re.sub(r"(?<![\w.\[-]):root\b", f".{RAIZ}", css)
        css = re.sub(r"(?m)^(\s*)\*\s*\{", rf"\1.{RAIZ} *, .{RAIZ} {{", css)
        css = re.sub(r"(?m)^(\s*)body\s*\{", rf"\1.{RAIZ} {{", css)
        # El resto de selectores se anidan bajo la raiz.
        def anidar(m):
            sel = m.group(1).strip()
            if sel.startswith(("@", f".{RAIZ}", "}")) or not sel:
                return m.group(0)
            piezas = [
                s.strip() if s.strip().startswith(f".{RAIZ}") else f".{RAIZ} {s.strip()}"
                for s in sel.split(",")
            ]
            return ", ".join(piezas) + " {"
        css = re.sub(r"(?m)^\s{2}([^@{}\n][^{\n]*)\{", anidar, css)
        # Minificar: la pagina se republica seguido, cada KB cuenta.
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        css = re.sub(r"\s*\n\s*", " ", css)
        css = re.sub(r"\s*([{};:,>])\s*", r"\1", css)
        css = re.sub(r";}", "}", css).strip()
        partes.append(f"<style>{css}</style>")

    if cuerpo:
        limpio = re.sub(r"<script>.*?</script>", "", cuerpo.group(1), flags=re.S)
        partes.append(f'<div class="{RAIZ}">{limpio}</div>')

    if script:
        partes.append(f"<script>{script.group(1)}</script>")

    partes.append("<!-- /wp:html -->")
    return "\n".join(partes)


def buscar_pagina(env, headers):
    """Devuelve el ID de la pagina. Prefiere el configurado, luego el conocido."""
    if env.get("WP_PAGE_ID"):
        return int(env["WP_PAGE_ID"])
    if PAGE_ID:
        return PAGE_ID
    r = requests.get(
        f"{SITIO}/wp-json/wp/v2/pages",
        params={"slug": SLUG, "status": "publish,draft,private"},
        headers=headers, timeout=30,
    )
    r.raise_for_status()
    datos = r.json()
    return datos[0]["id"] if datos else None


def subir(ruta_html, cambios=None):
    hubo = bool(cambios)
    hacerlo, motivo = toca_publicar(hubo)
    if not hacerlo:
        print(f"Publicacion omitida: {motivo}")
        return None

    env = cargar_env()
    headers = cabeceras(env)
    contenido = envolver(Path(ruta_html).read_text(encoding="utf-8"))

    page_id = buscar_pagina(env, headers)
    cuerpo = {
        "title": TITULO,
        "slug": SLUG,
        "content": contenido,
        "status": "publish",
    }

    if page_id:
        url = f"{SITIO}/wp-json/wp/v2/pages/{page_id}"
    else:
        url = f"{SITIO}/wp-json/wp/v2/pages"

    r = requests.post(url, headers=headers, data=json.dumps(cuerpo), timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"WordPress respondio {r.status_code}: {r.text[:300]}")

    MARCA.write_text(datetime.datetime.now().isoformat(), encoding="utf-8")
    enlace = r.json().get("link", f"{SITIO}/{SLUG}")
    print(f"Publicado ({motivo}): {enlace}")
    return enlace


if __name__ == "__main__":
    subir(BASE / "dashboard-publico.html", cambios=["manual"])
