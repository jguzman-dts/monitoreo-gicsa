#!/usr/bin/env python3
"""
Auditor de sitios de clientes DTS.

Lee las fichas de cliente del vault de Obsidian, extrae el campo `sitio_web`
del frontmatter y audita cada sitio. Escribe un reporte por cliente en
`20-Clientes/Auditorias/` y deja los hallazgos como pendientes en checkbox
para que la tarea diaria de la 1 PM los recoja.

Uso:
    python3 auditor.py                 # audita todos los clientes con sitio_web
    python3 auditor.py "Class Education"   # audita solo uno
    python3 auditor.py --dry-run       # muestra en pantalla, no escribe nada
"""

import re
import ssl
import time
import sys
import json
import socket
import datetime
from pathlib import Path
from urllib.parse import urlparse, urljoin

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit(
        "Faltan dependencias. Instala con:\n"
        "    pip3 install --user requests beautifulsoup4\n"
    )

VAULT = Path("/mnt/c/Obsidian/DTSLOCAL")
CLIENTES = VAULT / "20-Clientes"
SALIDA = CLIENTES / "Auditorias"

TIMEOUT = 20
UA = "Mozilla/5.0 (compatible; DTS-Auditor/1.0; +https://digitalts.com.mx)"

# Frases que delatan un dominio estacionado o en venta.
SENALES_PARKED = [
    "is parked free", "domain is parked", "this domain is for sale",
    "get this domain", "buy this domain", "dominio en venta",
    "parkingcrew", "sedoparking", "hugedomains", "afternic",
    "courtesy of", "domain for sale",
]

# Umbrales de alerta
DIAS_SSL_ALERTA = 30
SEGUNDOS_LENTO = 3.0
KB_PESADO = 3000
MESES_CONTENIDO_VIEJO = 12


# ---------------------------------------------------------------- utilidades

def log(msg):
    print(msg, flush=True)


def hoy():
    return datetime.date.today().isoformat()


def leer_frontmatter(texto):
    """Devuelve el frontmatter YAML como dict plano (sin dependencias)."""
    if not texto.startswith("---"):
        return {}
    fin = texto.find("\n---", 3)
    if fin == -1:
        return {}
    datos = {}
    for linea in texto[3:fin].splitlines():
        if ":" not in linea or linea.strip().startswith("#"):
            continue
        clave, _, valor = linea.partition(":")
        datos[clave.strip()] = valor.strip().strip('"').strip("'")
    return datos


def normalizar_url(valor):
    valor = valor.strip()
    if not valor or valor in ("[]", "~", "null"):
        return None
    if not valor.startswith(("http://", "https://")):
        valor = "https://" + valor
    return valor


# ------------------------------------------------------------------ chequeos

def revisar_dns(host):
    try:
        _, _, ips = socket.gethostbyname_ex(host)
        return {"ok": True, "ips": ips}
    except socket.gaierror as e:
        return {"ok": False, "error": str(e), "ips": []}


def revisar_ssl(host, puerto=443):
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, puerto), timeout=TIMEOUT) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert()
        vence = datetime.datetime.strptime(
            cert["notAfter"], "%b %d %H:%M:%S %Y %Z"
        ).date()
        emisor = dict(x[0] for x in cert.get("issuer", []))
        return {
            "ok": True,
            "vence": vence.isoformat(),
            "dias_restantes": (vence - datetime.date.today()).days,
            "emisor": emisor.get("organizationName", "desconocido"),
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def revisar_http(url):
    """Sigue redirecciones y mide tiempo y peso."""
    try:
        # Reloj monotonico: la hora del sistema puede saltar hacia atras
        # (WSL2 resincroniza tras suspender) y dar duraciones negativas.
        inicio = time.monotonic()
        r = requests.get(
            url, timeout=TIMEOUT, headers={"User-Agent": UA}, allow_redirects=True
        )
        segundos = time.monotonic() - inicio
        cadena = [f"{h.status_code} → {h.headers.get('Location', '?')}" for h in r.history]
        return {
            "ok": True,
            "status": r.status_code,
            "url_final": r.url,
            "redirecciones": cadena,
            "segundos": round(segundos, 2),
            "kb": round(len(r.content) / 1024, 1),
            "html": r.text,
        }
    except requests.exceptions.SSLError as e:
        return {"ok": False, "error": f"Error SSL: {e}"}
    except requests.exceptions.ConnectTimeout:
        return {"ok": False, "error": f"Timeout de conexion ({TIMEOUT}s)"}
    except requests.exceptions.ConnectionError as e:
        return {"ok": False, "error": f"No responde: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def revisar_www(url):
    """Compara el dominio con y sin www: un desajuste pierde trafico."""
    p = urlparse(url)
    host = p.netloc
    apex = host[4:] if host.startswith("www.") else host
    resultado = {}
    for etiqueta, h in (("apex", apex), ("www", "www." + apex)):
        dns = revisar_dns(h)
        if not dns["ok"]:
            resultado[etiqueta] = {"host": h, "estado": "sin DNS"}
            continue
        r = revisar_http(f"https://{h}")
        resultado[etiqueta] = {
            "host": h,
            "ips": dns["ips"],
            "estado": f"HTTP {r['status']}" if r["ok"] else r["error"],
            "url_final": r.get("url_final", ""),
        }
    return resultado


def detectar_parked(html):
    bajo = html.lower()
    return [s for s in SENALES_PARKED if s in bajo]


def analizar_seo(html, url_base):
    sopa = BeautifulSoup(html, "html.parser")

    title = sopa.title.string.strip() if sopa.title and sopa.title.string else None
    desc_tag = sopa.find("meta", attrs={"name": "description"})
    desc = desc_tag.get("content", "").strip() if desc_tag else None
    h1s = [h.get_text(strip=True) for h in sopa.find_all("h1")]

    og = {
        t.get("property"): t.get("content")
        for t in sopa.find_all("meta", property=re.compile(r"^og:"))
    }
    canonical = sopa.find("link", rel="canonical")
    viewport = sopa.find("meta", attrs={"name": "viewport"})

    imgs = sopa.find_all("img")
    sin_alt = [i.get("src", "?") for i in imgs if not i.get("alt", "").strip()]

    enlaces = set()
    for a in sopa.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        enlaces.add(urljoin(url_base, href))

    return {
        "title": title,
        "title_largo": len(title) if title else 0,
        "description": desc,
        "desc_largo": len(desc) if desc else 0,
        "h1": h1s,
        "og": og,
        "canonical": canonical.get("href") if canonical else None,
        "viewport": bool(viewport),
        "imgs_total": len(imgs),
        "imgs_sin_alt": len(sin_alt),
        "enlaces": sorted(enlaces),
    }


def buscar_fechas(html):
    """Detecta la fecha mas reciente publicada en la pagina."""
    meses = {
        "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
        "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10,
        "noviembre": 11, "diciembre": 12,
    }
    encontradas = []

    for m in re.finditer(r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", html, re.I):
        dia, mes, anio = m.group(1), m.group(2).lower(), m.group(3)
        if mes in meses:
            try:
                encontradas.append(datetime.date(int(anio), meses[mes], int(dia)))
            except ValueError:
                pass

    for m in re.finditer(r"(\d{4})-(\d{2})-(\d{2})", html):
        try:
            f = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if 2000 < f.year <= datetime.date.today().year:
                encontradas.append(f)
        except ValueError:
            pass

    return max(encontradas) if encontradas else None


def revisar_enlaces(enlaces, limite=25):
    """Muestrea enlaces internos y reporta los rotos."""
    rotos = []
    for url in enlaces[:limite]:
        try:
            r = requests.head(
                url, timeout=10, headers={"User-Agent": UA}, allow_redirects=True
            )
            if r.status_code >= 400:
                r = requests.get(url, timeout=10, headers={"User-Agent": UA})
            if r.status_code >= 400:
                rotos.append((url, r.status_code))
        except Exception as e:
            rotos.append((url, type(e).__name__))
    return rotos, min(len(enlaces), limite)


def revisar_extras(url):
    """robots.txt y sitemap.xml"""
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    salida = {}
    for nombre in ("robots.txt", "sitemap.xml"):
        try:
            r = requests.get(
                f"{base}/{nombre}", timeout=10, headers={"User-Agent": UA}
            )
            salida[nombre] = r.status_code
        except Exception:
            salida[nombre] = "error"
    return salida


# ---------------------------------------------------------------- auditoria

def auditar(cliente, url):
    log(f"\n=== {cliente} — {url} ===")
    host = urlparse(url).netloc
    r = {"cliente": cliente, "url": url, "host": host, "fecha": hoy(), "alertas": []}

    log("  · DNS")
    r["dns"] = revisar_dns(host)
    if not r["dns"]["ok"]:
        r["alertas"].append(("🔴", f"El dominio `{host}` no resuelve en DNS"))
        return r

    log("  · www vs apex")
    r["www"] = revisar_www(url)

    log("  · SSL")
    r["ssl"] = revisar_ssl(host)
    if not r["ssl"]["ok"]:
        r["alertas"].append(("🔴", f"No se pudo validar el certificado SSL: {r['ssl']['error']}"))
    elif r["ssl"]["dias_restantes"] < 0:
        r["alertas"].append(("🔴", f"El certificado SSL **ya vencio** ({r['ssl']['vence']})"))
    elif r["ssl"]["dias_restantes"] < DIAS_SSL_ALERTA:
        r["alertas"].append(
            ("🟡", f"El certificado SSL vence en {r['ssl']['dias_restantes']} dias ({r['ssl']['vence']})")
        )

    log("  · HTTP")
    http = revisar_http(url)
    r["http"] = {k: v for k, v in http.items() if k != "html"}
    if not http["ok"]:
        r["alertas"].append(("🔴", f"El sitio no responde: {http['error']}"))
        return r
    if http["status"] >= 400:
        r["alertas"].append(("🔴", f"El sitio devuelve HTTP {http['status']}"))
        return r
    if http["segundos"] > SEGUNDOS_LENTO:
        r["alertas"].append(
            ("🟡", f"Carga lenta: {http['segundos']}s (umbral {SEGUNDOS_LENTO}s)")
        )
    if http["kb"] > KB_PESADO:
        r["alertas"].append(("🟡", f"Pagina pesada: {http['kb']} KB"))

    log("  · dominio estacionado")
    senales = detectar_parked(http["html"])
    if senales:
        r["parked"] = senales
        r["alertas"].append(
            ("🔴", f"**El dominio parece estacionado o en venta**, no es un sitio real. Señales: {', '.join(senales[:3])}")
        )
        return r

    log("  · SEO")
    seo = analizar_seo(http["html"], http["url_final"])
    r["seo"] = {k: v for k, v in seo.items() if k != "enlaces"}
    if not seo["title"]:
        r["alertas"].append(("🔴", "La pagina no tiene etiqueta `<title>`"))
    elif seo["title_largo"] > 60:
        r["alertas"].append(("🟡", f"Title de {seo['title_largo']} caracteres — Google corta cerca de 60"))
    if not seo["description"]:
        r["alertas"].append(("🟡", "Falta la meta description"))
    elif seo["desc_largo"] > 160:
        r["alertas"].append(("🟡", f"Meta description de {seo['desc_largo']} caracteres — se corta cerca de 160"))
    if not seo["h1"]:
        r["alertas"].append(("🟡", "La pagina no tiene ningun `<h1>`"))
    elif len(seo["h1"]) > 1:
        r["alertas"].append(("🟡", f"Hay {len(seo['h1'])} etiquetas `<h1>` — deberia haber una sola"))
    if seo["title"]:
        # Marca repetida en el title: suele ser el CMS agregando el sufijo
        # a un titulo que ya lo traia.
        partes = [p.strip().lower() for p in re.split(r"[|\-–—·]", seo["title"]) if p.strip()]
        repetidas = {p for p in partes if partes.count(p) > 1}
        if repetidas:
            r["alertas"].append(
                ("🟡", f"El title repite «{list(repetidas)[0]}» dos veces — probablemente el CMS "
                       "agrega el nombre del sitio a un title que ya lo incluia")
            )

    if seo["canonical"]:
        # Un canonical que apunta a otra URL que la servida manda a Google
        # senales contradictorias sobre cual pagina indexar.
        can = seo["canonical"].rstrip("/")
        final = http["url_final"].rstrip("/")
        if can != final:
            r["alertas"].append(
                ("🔴", f"El canonical apunta a `{can}` pero la pagina se sirve en `{final}`. "
                       "Google recibe señales contradictorias sobre cual indexar.")
            )

    if not seo["og"]:
        r["alertas"].append(("🟡", "Sin Open Graph — al compartir en redes se ve sin imagen ni titulo"))
    if not seo["viewport"]:
        r["alertas"].append(("🔴", "Sin meta viewport — la pagina no es responsiva en movil"))
    if seo["imgs_sin_alt"]:
        r["alertas"].append(
            ("🟡", f"{seo['imgs_sin_alt']} de {seo['imgs_total']} imagenes sin texto alternativo")
        )

    log("  · frescura de contenido")
    fecha = buscar_fechas(http["html"])
    if fecha:
        r["ultima_fecha"] = fecha.isoformat()
        meses = (datetime.date.today() - fecha).days / 30.44
        r["meses_sin_publicar"] = round(meses, 1)
        if meses > MESES_CONTENIDO_VIEJO:
            r["alertas"].append(
                ("🟡", f"El contenido mas reciente que se detecta es del {fecha.isoformat()} — "
                       f"{round(meses)} meses sin actualizar")
            )

    log("  · enlaces")
    rotos, revisados = revisar_enlaces(seo["enlaces"])
    r["enlaces_revisados"] = revisados
    r["enlaces_totales"] = len(seo["enlaces"])
    r["enlaces_rotos"] = rotos
    if rotos:
        r["alertas"].append(("🟡", f"{len(rotos)} enlaces rotos de {revisados} revisados"))

    log("  · robots y sitemap")
    r["extras"] = revisar_extras(http["url_final"])
    if r["extras"].get("sitemap.xml") != 200:
        r["alertas"].append(("🟡", "No se encontro `sitemap.xml`"))

    # www vs apex: si uno funciona y el otro no, hay trafico perdiendose
    w = r.get("www", {})
    est_apex = w.get("apex", {}).get("estado", "")
    est_www = w.get("www", {}).get("estado", "")
    if est_apex.startswith("HTTP 2") and not est_www.startswith("HTTP 2"):
        r["alertas"].append(
            ("🔴", f"`www.{w['apex']['host']}` no funciona ({est_www}) pero el dominio sin www si. "
                   "Quien escriba www no llega al sitio.")
        )
    elif est_www.startswith("HTTP 2") and not est_apex.startswith("HTTP 2"):
        r["alertas"].append(
            ("🔴", f"`{w['apex']['host']}` sin www no funciona ({est_apex}) pero con www si.")
        )

    return r


# ------------------------------------------------------------------ reporte

def escribir_reporte(r):
    SALIDA.mkdir(parents=True, exist_ok=True)
    destino = SALIDA / f"{r['cliente']} — {r['fecha']}.md"

    criticas = [a for a in r["alertas"] if a[0] == "🔴"]
    avisos = [a for a in r["alertas"] if a[0] == "🟡"]

    L = []
    L.append("---")
    L.append("tipo: auditoria")
    L.append(f"cliente: \"{r['cliente']}\"")
    L.append(f"fecha: {r['fecha']}")
    L.append(f"sitio: {r['url']}")
    L.append(f"criticas: {len(criticas)}")
    L.append(f"avisos: {len(avisos)}")
    L.append("tags: [auditoria]")
    L.append("---")
    L.append("")
    L.append(f"# Auditoria — {r['cliente']}")
    L.append("")
    L.append(f"**Sitio:** {r['url']} · **Fecha:** {r['fecha']}")
    L.append(f"**Cliente:** [[{r['cliente']}]]")
    L.append("")

    if not r["alertas"]:
        L.append("✅ **Sin hallazgos.** El sitio pasó todas las revisiones.")
    else:
        L.append(f"## Resumen: {len(criticas)} criticas · {len(avisos)} avisos")
        L.append("")
        for icono, texto in criticas + avisos:
            L.append(f"- {icono} {texto}")
    L.append("")

    if r.get("http", {}).get("ok"):
        h = r["http"]
        L.append("## Respuesta")
        L.append("")
        L.append("| | |")
        L.append("|---|---|")
        L.append(f"| Estado | HTTP {h['status']} |")
        L.append(f"| URL final | {h['url_final']} |")
        L.append(f"| Tiempo de carga | {h['segundos']} s |")
        L.append(f"| Peso | {h['kb']} KB |")
        if h["redirecciones"]:
            L.append(f"| Redirecciones | {len(h['redirecciones'])} |")
        L.append("")

    if r.get("www"):
        L.append("## Dominio con y sin www")
        L.append("")
        L.append("| Variante | Host | Estado | IPs |")
        L.append("|---|---|---|---|")
        for etiqueta in ("apex", "www"):
            d = r["www"].get(etiqueta, {})
            ips = ", ".join(d.get("ips", [])) or "—"
            L.append(f"| {etiqueta} | `{d.get('host','?')}` | {d.get('estado','?')} | {ips} |")
        L.append("")

    if r.get("ssl", {}).get("ok"):
        s = r["ssl"]
        L.append("## Certificado SSL")
        L.append("")
        L.append(f"- Vence: **{s['vence']}** ({s['dias_restantes']} dias)")
        L.append(f"- Emisor: {s['emisor']}")
        L.append("")

    if r.get("seo"):
        s = r["seo"]
        L.append("## SEO en portada")
        L.append("")
        L.append("| Elemento | Valor |")
        L.append("|---|---|")
        L.append(f"| Title | {s['title'] or '**ausente**'} ({s['title_largo']} car.) |")
        L.append(f"| Description | {(s['description'] or '**ausente**')[:120]} ({s['desc_largo']} car.) |")
        L.append(f"| H1 | {' · '.join(s['h1']) if s['h1'] else '**ninguno**'} |")
        L.append(f"| Canonical | {s['canonical'] or '—'} |")
        L.append(f"| Open Graph | {'si (' + str(len(s['og'])) + ' etiquetas)' if s['og'] else '**no**'} |")
        L.append(f"| Viewport movil | {'si' if s['viewport'] else '**no**'} |")
        L.append(f"| Imagenes sin alt | {s['imgs_sin_alt']} de {s['imgs_total']} |")
        L.append("")

    if r.get("ultima_fecha"):
        L.append("## Frescura de contenido")
        L.append("")
        L.append(f"Fecha mas reciente detectada: **{r['ultima_fecha']}** "
                 f"({r.get('meses_sin_publicar','?')} meses)")
        L.append("")

    if r.get("enlaces_rotos"):
        L.append("## Enlaces rotos")
        L.append("")
        L.append(f"Revisados {r['enlaces_revisados']} de {r['enlaces_totales']} enlaces.")
        L.append("")
        for url, estado in r["enlaces_rotos"]:
            L.append(f"- `{estado}` — {url}")
        L.append("")

    if r.get("extras"):
        L.append("## Archivos tecnicos")
        L.append("")
        for k, v in r["extras"].items():
            L.append(f"- `{k}`: {v}")
        L.append("")

    if r["alertas"]:
        L.append("## Pendientes")
        L.append("")
        for icono, texto in criticas + avisos:
            limpio = texto.replace("**", "")
            L.append(f"- [ ] {icono} {limpio} — [[{r['cliente']}]]")
        L.append("")

    L.append("---")
    L.append(f"*Generado por el auditor DTS el {r['fecha']}.*")

    destino.write_text("\n".join(L), encoding="utf-8")
    return destino


# --------------------------------------------------------------------- main

def cargar_clientes(filtro=None):
    pendientes = []
    if not CLIENTES.exists():
        sys.exit(f"No encuentro la carpeta de clientes: {CLIENTES}")
    for f in sorted(CLIENTES.glob("*.md")):
        fm = leer_frontmatter(f.read_text(encoding="utf-8"))
        if fm.get("tipo") != "cliente":
            continue
        nombre = fm.get("nombre") or f.stem
        if filtro and filtro.lower() not in nombre.lower():
            continue
        url = normalizar_url(fm.get("sitio_web", ""))
        pendientes.append((nombre, url))
    return pendientes


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    filtro = args[0] if args else None

    clientes = cargar_clientes(filtro)
    if not clientes:
        sys.exit("No hay clientes que auditar.")

    con_sitio = [(n, u) for n, u in clientes if u]
    sin_sitio = [n for n, u in clientes if not u]

    log(f"Clientes encontrados: {len(clientes)}")
    if sin_sitio:
        log(f"Sin `sitio_web` en el frontmatter (se omiten): {', '.join(sin_sitio)}")
    if not con_sitio:
        sys.exit("Ningun cliente tiene el campo `sitio_web` configurado.")

    resultados = []
    for nombre, url in con_sitio:
        try:
            r = auditar(nombre, url)
        except Exception as e:
            log(f"  ! Error auditando {nombre}: {type(e).__name__}: {e}")
            continue
        resultados.append(r)
        if dry:
            log(json.dumps(
                {k: v for k, v in r.items() if k != "http"},
                indent=2, ensure_ascii=False, default=str
            ))
        else:
            destino = escribir_reporte(r)
            log(f"  → {destino.name}")

    log("\n" + "=" * 60)
    for r in resultados:
        c = sum(1 for a in r["alertas"] if a[0] == "🔴")
        v = sum(1 for a in r["alertas"] if a[0] == "🟡")
        estado = "OK" if not r["alertas"] else f"{c} criticas, {v} avisos"
        log(f"{r['cliente']:<25} {estado}")
    log("=" * 60)


if __name__ == "__main__":
    main()
