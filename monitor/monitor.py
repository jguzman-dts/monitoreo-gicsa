#!/usr/bin/env python3
"""
Monitor de disponibilidad de sitios — DTS.

Revisa cada sitio de `sitios.json`, guarda el resultado en un historial,
detecta cambios de estado (caida / recuperacion / degradacion) y los
registra en una bitacora markdown dentro del vault de Obsidian.

Solo escribe en la bitacora cuando algo CAMBIA. Un sitio que lleva
semanas arriba no genera ruido.

Uso:
    python3 monitor.py              # revisa todos y actualiza bitacora
    python3 monitor.py --once       # revisa y muestra, sin escribir
    python3 monitor.py --dashboard  # revisa y ademas regenera el dashboard
"""

import re
import ssl
import sys
import json
import socket
import datetime
import concurrent.futures as futures
from pathlib import Path
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    sys.exit("Falta requests. Instala con: ~/dts-venv/bin/pip install requests")

BASE = Path(__file__).resolve().parent
VAULT = Path("/mnt/c/Obsidian/DTSLOCAL")
CONFIG = BASE / "sitios.json"
HISTORIAL = BASE / "historial.jsonl"
ESTADO = BASE / "estado.json"

TIMEOUT = 25
UA = "Mozilla/5.0 (compatible; DTS-Monitor/1.0; +https://digitalts.com.mx)"
HILOS = 6

SEGUNDOS_LENTO = 4.0
DIAS_SSL_ALERTA = 30

SENALES_PARKED = [
    "is parked free", "domain is parked", "this domain is for sale",
    "get this domain", "buy this domain", "dominio en venta",
    "parkingcrew", "sedoparking", "hugedomains", "afternic",
]

# Estados posibles, de mejor a peor
ARRIBA = "arriba"
LENTO = "lento"
DEGRADADO = "degradado"
CAIDO = "caido"

ICONO = {ARRIBA: "🟢", LENTO: "🟡", DEGRADADO: "🟠", CAIDO: "🔴"}


def ahora():
    return datetime.datetime.now()


def sello():
    return ahora().strftime("%Y-%m-%d %H:%M")


# ------------------------------------------------------------------ chequeos

def revisar_dns(host):
    try:
        _, _, ips = socket.gethostbyname_ex(host)
        return {"ok": True, "ips": sorted(ips)}
    except socket.gaierror as e:
        return {"ok": False, "error": str(e), "ips": []}


def revisar_ssl(host):
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=TIMEOUT) as s:
            with ctx.wrap_socket(s, server_hostname=host) as tls:
                cert = tls.getpeercert()
        vence = datetime.datetime.strptime(
            cert["notAfter"], "%b %d %H:%M:%S %Y %Z"
        ).date()
        return {
            "ok": True,
            "vence": vence.isoformat(),
            "dias": (vence - datetime.date.today()).days,
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}"}


def revisar(sitio):
    """Revisa un sitio y devuelve su estado normalizado."""
    url = sitio["url"]
    host = urlparse(url).netloc
    r = {
        "nombre": sitio["nombre"],
        "url": url,
        "host": host,
        "tipo": sitio.get("tipo", ""),
        "momento": sello(),
        "problemas": [],
    }

    dns = revisar_dns(host)
    r["ips"] = dns["ips"]
    if not dns["ok"]:
        r["estado"] = CAIDO
        r["detalle"] = f"El dominio no resuelve en DNS ({dns['error']})"
        r["problemas"].append("DNS no resuelve")
        return r

    try:
        t0 = ahora()
        resp = requests.get(
            url, timeout=TIMEOUT, headers={"User-Agent": UA}, allow_redirects=True
        )
        segundos = (ahora() - t0).total_seconds()
    except requests.exceptions.SSLError as e:
        r["estado"] = CAIDO
        r["detalle"] = f"Error de certificado SSL: {str(e)[:120]}"
        r["problemas"].append("SSL invalido")
        return r
    except requests.exceptions.ConnectTimeout:
        r["estado"] = CAIDO
        r["detalle"] = f"Timeout de conexion tras {TIMEOUT}s"
        r["problemas"].append("Timeout")
        return r
    except requests.exceptions.ConnectionError as e:
        r["estado"] = CAIDO
        r["detalle"] = f"No responde: {str(e)[:120]}"
        r["problemas"].append("Sin respuesta")
        return r
    except Exception as e:
        r["estado"] = CAIDO
        r["detalle"] = f"{type(e).__name__}: {str(e)[:120]}"
        r["problemas"].append(type(e).__name__)
        return r

    r["status"] = resp.status_code
    r["segundos"] = round(segundos, 2)
    r["url_final"] = resp.url
    r["kb"] = round(len(resp.content) / 1024, 1)
    r["redirecciones"] = len(resp.history)

    ssl_info = revisar_ssl(host)
    r["ssl"] = ssl_info
    if ssl_info["ok"] and ssl_info["dias"] < 0:
        r["problemas"].append("Certificado SSL vencido")
    elif ssl_info["ok"] and ssl_info["dias"] < DIAS_SSL_ALERTA:
        r["problemas"].append(f"SSL vence en {ssl_info['dias']} dias")

    bajo = resp.text.lower()
    parked = [s for s in SENALES_PARKED if s in bajo]
    if parked:
        r["estado"] = DEGRADADO
        r["detalle"] = "El dominio parece estacionado o en venta, no es un sitio real"
        r["problemas"].append("Dominio estacionado")
        return r

    if resp.status_code >= 500:
        r["estado"] = CAIDO
        r["detalle"] = f"Error del servidor: HTTP {resp.status_code}"
        r["problemas"].append(f"HTTP {resp.status_code}")
    elif resp.status_code >= 400:
        r["estado"] = DEGRADADO
        r["detalle"] = f"HTTP {resp.status_code}"
        r["problemas"].append(f"HTTP {resp.status_code}")
    elif len(resp.content) < 1024:
        r["estado"] = DEGRADADO
        r["detalle"] = f"Responde 200 pero la pagina esta casi vacia ({r['kb']} KB)"
        r["problemas"].append("Pagina vacia")
    elif segundos > SEGUNDOS_LENTO:
        r["estado"] = LENTO
        r["detalle"] = f"Responde en {r['segundos']}s (umbral {SEGUNDOS_LENTO}s)"
        r["problemas"].append("Lento")
    else:
        r["estado"] = ARRIBA
        r["detalle"] = f"HTTP {resp.status_code} en {r['segundos']}s"

    # Titulo, util para confirmar que carga el sitio correcto
    m = re.search(r"<title[^>]*>(.*?)</title>", resp.text, re.I | re.S)
    if m:
        r["titulo"] = re.sub(r"\s+", " ", m.group(1)).strip()[:120]

    return r


# ------------------------------------------------------------- persistencia

def cargar_estado_previo():
    if ESTADO.exists():
        try:
            return json.loads(ESTADO.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def guardar(resultados):
    estado = {r["url"]: r for r in resultados}
    ESTADO.write_text(
        json.dumps(estado, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    with HISTORIAL.open("a", encoding="utf-8") as f:
        for r in resultados:
            f.write(json.dumps(
                {k: v for k, v in r.items() if k != "titulo"},
                ensure_ascii=False
            ) + "\n")


def detectar_cambios(resultados, previo):
    """Devuelve solo los sitios cuyo estado cambio desde la ultima corrida."""
    cambios = []
    for r in resultados:
        antes = previo.get(r["url"], {}).get("estado")
        if antes is None:
            cambios.append(("nuevo", r, None))
        elif antes != r["estado"]:
            tipo = "recuperacion" if r["estado"] == ARRIBA else "cambio"
            if antes == ARRIBA and r["estado"] == CAIDO:
                tipo = "caida"
            cambios.append((tipo, r, antes))
    return cambios


# ---------------------------------------------------------------- bitacora

def escribir_bitacora(cliente, resultados, cambios):
    carpeta = VAULT / "20-Clientes" / "Monitoreo"
    carpeta.mkdir(parents=True, exist_ok=True)
    archivo = carpeta / f"{cliente} — Bitacora de monitoreo.md"

    caidos = [r for r in resultados if r["estado"] == CAIDO]
    degradados = [r for r in resultados if r["estado"] == DEGRADADO]
    lentos = [r for r in resultados if r["estado"] == LENTO]
    arriba = [r for r in resultados if r["estado"] == ARRIBA]

    # --- Cabecera, se reescribe cada corrida ---
    cab = []
    cab.append("---")
    cab.append("tipo: monitoreo")
    cab.append(f'cliente: "{cliente}"')
    cab.append(f"ultima_revision: {sello()}")
    cab.append(f"sitios: {len(resultados)}")
    cab.append(f"caidos: {len(caidos)}")
    cab.append(f"degradados: {len(degradados)}")
    cab.append(f"lentos: {len(lentos)}")
    cab.append("tags: [monitoreo]")
    cab.append("---")
    cab.append("")
    cab.append(f"# Monitoreo — {cliente}")
    cab.append("")
    cab.append(f"**Última revisión:** {sello()} · **Cliente:** [[{cliente}]]")
    cab.append("")

    if caidos or degradados:
        cab.append(f"> [!warning] {len(caidos)} caídos · {len(degradados)} degradados · "
                   f"{len(lentos)} lentos · {len(arriba)} en orden")
    else:
        cab.append(f"> [!success] Los {len(resultados)} sitios responden correctamente")
    cab.append("")

    cab.append("## Estado actual")
    cab.append("")
    cab.append("| | Sitio | Estado | Respuesta | SSL | Detalle |")
    cab.append("|---|---|---|---|---|---|")
    orden = {CAIDO: 0, DEGRADADO: 1, LENTO: 2, ARRIBA: 3}
    for r in sorted(resultados, key=lambda x: (orden[x["estado"]], x["nombre"])):
        s = r.get("ssl", {})
        ssl_txt = f"{s['dias']}d" if s.get("ok") else "—"
        tiempo = f"{r['segundos']}s" if "segundos" in r else "—"
        cab.append(
            f"| {ICONO[r['estado']]} | [{r['nombre']}]({r['url']}) | {r['estado']} | "
            f"{tiempo} | {ssl_txt} | {r['detalle']} |"
        )
    cab.append("")

    if caidos or degradados:
        cab.append("## Pendientes de atención")
        cab.append("")
        for r in caidos + degradados:
            cab.append(f"- [ ] {ICONO[r['estado']]} **{r['nombre']}** — {r['detalle']} — [[{cliente}]]")
        cab.append("")

    cab.append("## Historial de incidencias")
    cab.append("")
    cab.append("> Solo se registran los **cambios de estado**. Un sitio estable no genera entradas.")
    cab.append("")

    cabecera = "\n".join(cab)

    # --- Historial, se conserva y se le antepone lo nuevo ---
    previo_hist = ""
    if archivo.exists():
        texto = archivo.read_text(encoding="utf-8")
        marca = "## Historial de incidencias"
        if marca in texto:
            resto = texto.split(marca, 1)[1]
            # quitar la nota introductoria para no duplicarla
            lineas = [
                l for l in resto.splitlines()
                if not l.startswith("> Solo se registran")
            ]
            previo_hist = "\n".join(lineas).strip()

    nuevas = []
    if cambios:
        nuevas.append(f"### {sello()}")
        nuevas.append("")
        for tipo, r, antes in cambios:
            if tipo == "nuevo":
                nuevas.append(
                    f"- {ICONO[r['estado']]} **{r['nombre']}** — primera revisión: "
                    f"{r['estado']}. {r['detalle']}"
                )
            elif tipo == "caida":
                nuevas.append(
                    f"- 🔴 **{r['nombre']} CAYÓ** — estaba `{antes}`, ahora `{r['estado']}`. "
                    f"{r['detalle']}"
                )
            elif tipo == "recuperacion":
                nuevas.append(
                    f"- ✅ **{r['nombre']} se recuperó** — estaba `{antes}`, ahora responde bien. "
                    f"{r['detalle']}"
                )
            else:
                nuevas.append(
                    f"- {ICONO[r['estado']]} **{r['nombre']}** — pasó de `{antes}` a "
                    f"`{r['estado']}`. {r['detalle']}"
                )
        nuevas.append("")

    cuerpo = "\n".join(nuevas) + previo_hist
    archivo.write_text(cabecera + cuerpo + "\n", encoding="utf-8")
    return archivo


# --------------------------------------------------------------------- main

def main():
    dry = "--once" in sys.argv
    hacer_dash = "--dashboard" in sys.argv

    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    cliente = cfg["cliente"]
    sitios = cfg["sitios"]

    print(f"Revisando {len(sitios)} sitios de {cliente}...\n")

    resultados = []
    with futures.ThreadPoolExecutor(max_workers=HILOS) as pool:
        for r in pool.map(revisar, sitios):
            resultados.append(r)
            s = r.get("ssl", {})
            ssl_txt = f"SSL {s['dias']}d" if s.get("ok") else "SSL —"
            tiempo = f"{r['segundos']:>5.2f}s" if "segundos" in r else "    —"
            print(f"  {ICONO[r['estado']]} {r['nombre']:<22} {tiempo}  {ssl_txt:<9} {r['detalle'][:60]}")

    resultados.sort(key=lambda x: x["nombre"])
    previo = cargar_estado_previo()
    cambios = detectar_cambios(resultados, previo)

    print("\n" + "=" * 72)
    for estado in (CAIDO, DEGRADADO, LENTO, ARRIBA):
        n = sum(1 for r in resultados if r["estado"] == estado)
        if n:
            print(f"  {ICONO[estado]} {estado}: {n}")
    print("=" * 72)

    if cambios:
        print(f"\n{len(cambios)} cambios de estado detectados:")
        for tipo, r, antes in cambios:
            print(f"  · {r['nombre']}: {antes or '(primera vez)'} → {r['estado']}")

    if dry:
        print("\n--once: no se escribio nada.")
        return

    guardar(resultados)
    archivo = escribir_bitacora(cliente, resultados, cambios)
    print(f"\nBitacora: {archivo}")

    if hacer_dash:
        try:
            import dashboard
            interno, publico = dashboard.generar_ambos(cliente, resultados, HISTORIAL)
            print(f"Dashboard interno: {interno}")
            print(f"Dashboard publico: {publico}")
        except ImportError:
            print("dashboard.py no encontrado, se omite.")

    if "--publicar" in sys.argv:
        try:
            import publicar
            publicar.subir(BASE / "dashboard-publico.html", cambios)
        except ImportError:
            print("publicar.py no encontrado, se omite la publicacion.")
        except Exception as e:
            print(f"No se pudo publicar: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
