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

        # --- Blindaje contra el tema del sitio ---
        # El tema de digitalts.com.mx fuerza `h3 {color:#1f1f1f}` y gana por
        # especificidad, dejando los nombres de los sitios en negro sobre el
        # fondo oscuro del dashboard: invisibles. Estas propiedades se marcan
        # !important para que el bloque se vea igual sin importar el tema.
        # No se tocan layout ni tamanos: solo lo que el tema pisa.
        BLINDAR = ("color", "background", "background-color", "border-color",
                   "border-left-color", "font", "font-size", "font-weight",
                   "font-family", "line-height", "text-transform",
                   "letter-spacing", "text-align", "margin", "padding")

        def marcar(m):
            prop, valor = m.group(1), m.group(2)
            if prop.strip().lower() in BLINDAR and "!important" not in valor:
                return f"{prop}:{valor.rstrip()}!important"
            return m.group(0)

        css = re.sub(r"([a-z-]+):([^;{}]+)(?=[;}])", marcar, css)

        css += (
            # --- Color heredado ---
            # El dashboard suelto no declara `color` en los encabezados: los
            # deja heredar del contenedor. El tema del sitio SI declara
            # `h3{color:#1f1f1f}` sobre el elemento, y un valor propio siempre
            # le gana a uno heredado — por eso los nombres salian en negro
            # sobre el fondo oscuro. Se declara explicitamente aqui.
            # Va antes que las reglas propias del dashboard en especificidad,
            # asi que .badge, .val.bien y demas conservan su color.
            f".{RAIZ} h1,.{RAIZ} h2,.{RAIZ} h3,.{RAIZ} h4,"
            f".{RAIZ} p,.{RAIZ} li,.{RAIZ} ol,.{RAIZ} ul,"
            f".{RAIZ} figure,.{RAIZ} figcaption,.{RAIZ} div,.{RAIZ} span"
            f"{{color:var(--texto)!important}}"
            # Los elementos que deben ir en tono apagado, ya con color propio.
            f".{RAIZ} figcaption,.{RAIZ} .l,.{RAIZ} .k,.{RAIZ} .meta,"
            f".{RAIZ} .detalle,.{RAIZ} .periodo,.{RAIZ} .val,.{RAIZ} .hh,"
            f".{RAIZ} .cuando,.{RAIZ} .pormenor,.{RAIZ} .ip,.{RAIZ} .pie,"
            f".{RAIZ} .pie span,.{RAIZ} .nota-escala,.{RAIZ} .vacio,"
            f".{RAIZ} .sitio a,.{RAIZ} .patron p"
            f"{{color:var(--suave)!important}}"

            # El header del sitio es position:fixed con 65px de alto y se
            # encimaba sobre el titulo del dashboard.
            f".{RAIZ}{{padding-top:96px!important;"
            f"position:relative;z-index:1;"
            f"border-radius:14px;overflow:hidden}}"
            # Que el ancho del tema no estrangule la rejilla.
            f".{RAIZ} .wrap{{max-width:100%!important}}"
            # Que el tema no meta listas con vinetas ni sangrias raras.
            f".{RAIZ} .linea{{list-style:none!important;padding-left:0!important}}"
            # Ocultar los botones de compartir de Jetpack si el tema los
            # vuelve a inyectar.
            "#jp-post-flair,.sharedaddy,.sd-sharing,.sd-block,"
            ".jp-relatedposts,.sd-like{display:none!important}"
        )

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
