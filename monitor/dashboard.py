#!/usr/bin/env python3
"""
Generador del dashboard de monitoreo — DTS.

Produce un HTML autocontenido (sin CDN, sin fuentes externas, sin JS de
terceros) para que pueda servirse localmente y tambien incrustarse en el
sitio de DTS mediante un iframe sin violar politicas de seguridad.

Se invoca desde monitor.py con --dashboard, o directo:
    python3 dashboard.py
"""

import json
import html
import datetime
from pathlib import Path
from collections import defaultdict

BASE = Path(__file__).resolve().parent
ESTADO = BASE / "estado.json"
HISTORIAL = BASE / "historial.jsonl"
SALIDA = BASE / "dashboard.html"

ICONO = {"arriba": "🟢", "lento": "🟡", "degradado": "🟠", "caido": "🔴"}
ETIQUETA = {
    "arriba": "En línea",
    "lento": "Lento",
    "degradado": "Degradado",
    "caido": "Caído",
}


def leer_historial(ruta, limite_por_sitio=60):
    """Devuelve {url: [registros...]} del mas viejo al mas nuevo."""
    por_sitio = defaultdict(list)
    if not ruta.exists():
        return por_sitio
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            r = json.loads(linea)
        except json.JSONDecodeError:
            continue
        por_sitio[r.get("url", "?")].append(r)
    return {u: v[-limite_por_sitio:] for u, v in por_sitio.items()}


def calcular_uptime(registros):
    if not registros:
        return None
    ok = sum(1 for r in registros if r.get("estado") in ("arriba", "lento"))
    return round(100 * ok / len(registros), 1)


def barra_historial(registros, maximo=40, publico=False):
    """Franja de cuadritos con el historial reciente, estilo status page.

    En modo publico el tooltip lleva solo la hora y el estado. El campo
    `detalle` trae el mensaje crudo del servidor —"Error del servidor:
    HTTP 502"— y eso es infraestructura del cliente, no informacion de
    disponibilidad.
    """
    recientes = registros[-maximo:]
    faltan = maximo - len(recientes)
    celdas = ['<i class="hx vacio"></i>'] * faltan
    for r in recientes:
        est = r.get("estado", "caido")
        momento = html.escape(r.get("momento", ""))
        if publico:
            titulo = f"{momento} — {ETIQUETA.get(est, est)}"
        else:
            titulo = f"{momento} — {html.escape(r.get('detalle', '')[:70])}"
        celdas.append(f'<i class="hx {est}" title="{titulo}"></i>')
    return "".join(celdas)


def sparkline(registros, ancho=150, alto=32):
    """Grafica de tiempos de respuesta en SVG puro."""
    puntos = [r.get("segundos") for r in registros if r.get("segundos") is not None]
    if len(puntos) < 2:
        return '<span class="nodata">sin datos suficientes</span>'
    tope = max(puntos) or 1
    paso = ancho / (len(puntos) - 1)
    coords = " ".join(
        f"{i * paso:.1f},{alto - (v / tope) * (alto - 4) - 2:.1f}"
        for i, v in enumerate(puntos)
    )
    return (
        f'<svg class="spark" viewBox="0 0 {ancho} {alto}" '
        f'preserveAspectRatio="none" role="img" '
        f'aria-label="Tiempo de respuesta, maximo {tope:.2f} segundos">'
        f'<polyline points="{coords}" />'
        f"</svg>"
    )


def generar(cliente, resultados=None, historial_path=HISTORIAL, salida=SALIDA,
            publico=False):
    """Genera el dashboard.

    publico=True omite todo lo que es infraestructura del cliente —IPs,
    proveedor de hosting, mensajes de error del servidor— y deja solo el
    estado de disponibilidad. Lo que se publica en un sitio abierto no debe
    darle a nadie un mapa de la infraestructura de GICSA.
    """
    if resultados is None:
        if not ESTADO.exists():
            raise SystemExit("No hay estado.json. Corre monitor.py primero.")
        resultados = list(json.loads(ESTADO.read_text(encoding="utf-8")).values())

    hist = leer_historial(historial_path)
    ahora = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")

    orden = {"caido": 0, "degradado": 1, "lento": 2, "arriba": 3}
    resultados = sorted(resultados, key=lambda r: (orden.get(r["estado"], 9), r["nombre"]))

    conteo = defaultdict(int)
    for r in resultados:
        conteo[r["estado"]] += 1

    total = len(resultados)
    con_problema = conteo["caido"] + conteo["degradado"]

    if conteo["caido"]:
        banner_clase, banner_txt = "critico", (
            f"{conteo['caido']} sitio{'s' if conteo['caido'] != 1 else ''} caído"
            f"{'s' if conteo['caido'] != 1 else ''}"
        )
    elif con_problema or conteo["lento"]:
        banner_clase, banner_txt = "aviso", "Operando con incidencias"
    else:
        banner_clase, banner_txt = "ok", "Todos los sitios operando"

    tarjetas = []
    for r in resultados:
        registros = hist.get(r["url"], [])
        up = calcular_uptime(registros)
        est = r["estado"]
        ssl = r.get("ssl", {})

        if ssl.get("ok"):
            d = ssl["dias"]
            ssl_clase = "mal" if d < 0 else ("alerta" if d < 30 else "bien")
            ssl_txt = "vencido" if d < 0 else f"{d} días"
        else:
            ssl_clase, ssl_txt = "mal", "sin validar"

        tiempo = f"{r['segundos']}s" if r.get("segundos") is not None else "—"

        # Estado del panel de WordPress
        admin = r.get("admin")
        if admin is None:
            chip_admin = ""
        elif admin.get("ok"):
            chip_admin = '<span class="chip bien" title="wp-login.php responde con formulario de acceso">Panel ✓</span>'
        else:
            det = (f"HTTP {admin['status']}" if admin.get("status")
                   else admin.get("error", "sin respuesta"))
            titulo = "El panel de WordPress no responde correctamente"
            chip_admin = (f'<span class="chip mal" title="{html.escape(titulo)}">'
                          f'Panel ✗{"" if publico else " · " + html.escape(det)}</span>')

        if publico:
            # Sin IPs, y el detalle se reduce a una frase neutra: el mensaje
            # crudo del servidor delata version, proveedor y modo de falla.
            pie_derecho = ""
            detalle = {
                "arriba": "Operando con normalidad",
                "lento": "Responde con lentitud",
                "degradado": "Servicio degradado",
                "caido": "Sin servicio — incidencia en atención",
            }.get(est, "")
            if admin is not None and not admin.get("ok"):
                detalle = "El sitio carga pero su panel de administración no responde"
            bloque_ssl = ""
        else:
            pie_derecho = f'<span class="ip">{html.escape(", ".join(r.get("ips", [])) or "—")}</span>'
            detalle = r.get("detalle", "")
            bloque_ssl = f'<div><span class="k">SSL</span><span class="v {ssl_clase}">{ssl_txt}</span></div>'

        tarjetas.append(f"""
      <article class="sitio {est}">
        <header>
          <span class="punto" aria-hidden="true"></span>
          <div class="ident">
            <h3>{html.escape(r['nombre'])}</h3>
            <a href="{html.escape(r['url'])}" target="_blank" rel="noopener noreferrer">{html.escape(r['host'])}</a>
          </div>
          <span class="badge">{ETIQUETA.get(est, est)}</span>
        </header>

        <p class="detalle">{html.escape(detalle)}</p>
        {f'<div class="chips">{chip_admin}</div>' if chip_admin else ''}

        <div class="metricas">
          <div><span class="k">Respuesta</span><span class="v">{tiempo}</span></div>
          <div><span class="k">Uptime</span><span class="v">{up if up is not None else '—'}{'%' if up is not None else ''}</span></div>
          {bloque_ssl}
        </div>

        <div class="historial" title="Historial de revisiones, la más reciente a la derecha">
          {barra_historial(registros, publico=publico)}
        </div>

        <footer>
          {sparkline(registros)}
          {pie_derecho}
        </footer>
      </article>""")

    return _escribir(
        salida, cliente, ahora, total, conteo, banner_clase, banner_txt,
        "\n".join(tarjetas), len(hist), publico,
        seccion_incidencias(publico, historial_path),
    )


def _escribir(salida, cliente, ahora, total, conteo, banner_clase, banner_txt,
              tarjetas, n_hist, publico=False, incidencias_html=""):
    # Marca de tiempo en ISO para que el navegador pueda calcular la antiguedad.
    generado_iso = datetime.datetime.now().astimezone().isoformat()
    cols_metricas = 2 if publico else 3

    doc = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<meta name="robots" content="noindex">
<title>Monitoreo {html.escape(cliente)} — DTS</title>
<style>
  :root {{
    --bg:#f6f7f9; --panel:#ffffff; --linea:#e3e6ea;
    --texto:#1a1d21; --suave:#646b75;
    --verde:#12a150; --amarillo:#d99000; --naranja:#e06c1f; --rojo:#d13438;
    --acento:#0a84ff;
    --sombra:0 1px 2px rgba(16,24,40,.05), 0 1px 3px rgba(16,24,40,.08);
    --radio:12px;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --bg:#0f1216; --panel:#171b21; --linea:#262c35;
      --texto:#e8eaed; --suave:#98a1ad;
      --verde:#3fb950; --amarillo:#d29922; --naranja:#db6d28; --rojo:#f85149;
      --sombra:0 1px 2px rgba(0,0,0,.4);
    }}
  }}
  :root[data-theme="dark"] {{
    --bg:#0f1216; --panel:#171b21; --linea:#262c35;
    --texto:#e8eaed; --suave:#98a1ad;
    --verde:#3fb950; --amarillo:#d29922; --naranja:#db6d28; --rojo:#f85149;
    --sombra:0 1px 2px rgba(0,0,0,.4);
  }}

  * {{ box-sizing:border-box; }}
  body {{
    margin:0; padding:24px;
    background:var(--bg); color:var(--texto);
    font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    -webkit-font-smoothing:antialiased;
  }}
  .wrap {{ max-width:1180px; margin:0 auto; }}

  .cabeza {{ display:flex; flex-wrap:wrap; gap:12px; align-items:baseline; justify-content:space-between; margin-bottom:18px; }}
  .cabeza h1 {{ margin:0; font-size:21px; font-weight:650; letter-spacing:-.01em; }}
  .cabeza .meta {{ color:var(--suave); font-size:13px; }}

  .banner {{
    display:flex; align-items:center; gap:11px;
    padding:14px 18px; border-radius:var(--radio); margin-bottom:20px;
    font-weight:600; border:1px solid transparent;
  }}
  .banner .pt {{ width:9px; height:9px; border-radius:50%; flex:none; }}
  .banner.ok       {{ background:color-mix(in srgb,var(--verde) 10%,var(--panel)); border-color:color-mix(in srgb,var(--verde) 30%,transparent); color:var(--verde); }}
  .banner.ok .pt   {{ background:var(--verde); }}
  .banner.aviso    {{ background:color-mix(in srgb,var(--amarillo) 10%,var(--panel)); border-color:color-mix(in srgb,var(--amarillo) 32%,transparent); color:var(--amarillo); }}
  .banner.aviso .pt{{ background:var(--amarillo); }}
  .banner.critico  {{ background:color-mix(in srgb,var(--rojo) 10%,var(--panel)); border-color:color-mix(in srgb,var(--rojo) 32%,transparent); color:var(--rojo); }}
  .banner.critico .pt {{ background:var(--rojo); animation:latido 1.6s ease-in-out infinite; }}
  @keyframes latido {{ 0%,100%{{opacity:1}} 50%{{opacity:.35}} }}
  @media (prefers-reduced-motion:reduce) {{ .banner.critico .pt {{ animation:none; }} }}

  .resumen {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:12px; margin-bottom:22px; }}
  .kpi {{ background:var(--panel); border:1px solid var(--linea); border-radius:var(--radio); padding:14px 16px; box-shadow:var(--sombra); }}
  .kpi .n {{ font-size:26px; font-weight:660; line-height:1.15; letter-spacing:-.02em; }}
  .kpi .l {{ font-size:12px; color:var(--suave); text-transform:uppercase; letter-spacing:.05em; margin-top:2px; }}
  .kpi.caido .n {{ color:var(--rojo); }}
  .kpi.degradado .n {{ color:var(--naranja); }}
  .kpi.lento .n {{ color:var(--amarillo); }}
  .kpi.arriba .n {{ color:var(--verde); }}

  .rejilla {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(330px,1fr)); gap:14px; }}

  .sitio {{ background:var(--panel); border:1px solid var(--linea); border-left-width:3px; border-radius:var(--radio); padding:15px 16px; box-shadow:var(--sombra); }}
  .sitio.arriba    {{ border-left-color:var(--verde); }}
  .sitio.lento     {{ border-left-color:var(--amarillo); }}
  .sitio.degradado {{ border-left-color:var(--naranja); }}
  .sitio.caido     {{ border-left-color:var(--rojo); }}

  .sitio header {{ display:flex; align-items:flex-start; gap:10px; margin-bottom:9px; }}
  .punto {{ width:8px; height:8px; border-radius:50%; margin-top:6px; flex:none; }}
  .arriba .punto {{ background:var(--verde); }}
  .lento .punto {{ background:var(--amarillo); }}
  .degradado .punto {{ background:var(--naranja); }}
  .caido .punto {{ background:var(--rojo); }}
  .ident {{ flex:1; min-width:0; }}
  .sitio h3 {{ margin:0; font-size:15px; font-weight:620; letter-spacing:-.01em; }}
  .sitio a {{ font-size:12.5px; color:var(--suave); text-decoration:none; word-break:break-all; }}
  .sitio a:hover {{ color:var(--acento); text-decoration:underline; }}

  .badge {{ font-size:11px; font-weight:640; padding:3px 9px; border-radius:99px; white-space:nowrap; flex:none; }}
  .arriba .badge {{ background:color-mix(in srgb,var(--verde) 14%,transparent); color:var(--verde); }}
  .lento .badge {{ background:color-mix(in srgb,var(--amarillo) 15%,transparent); color:var(--amarillo); }}
  .degradado .badge {{ background:color-mix(in srgb,var(--naranja) 15%,transparent); color:var(--naranja); }}
  .caido .badge {{ background:color-mix(in srgb,var(--rojo) 14%,transparent); color:var(--rojo); }}

  .detalle {{ margin:0 0 10px; font-size:13px; color:var(--suave); min-height:2.6em; }}

  .chips {{ display:flex; flex-wrap:wrap; gap:6px; margin-bottom:10px; }}
  .chip {{ font-size:10.5px; font-weight:640; padding:2px 8px; border-radius:5px; letter-spacing:.01em; }}
  .chip.bien {{ background:color-mix(in srgb,var(--verde) 13%,transparent); color:var(--verde); }}
  .chip.mal  {{ background:color-mix(in srgb,var(--rojo) 13%,transparent); color:var(--rojo); }}

  .obsoleto {{
    display:none; align-items:center; gap:11px;
    padding:14px 18px; border-radius:var(--radio); margin-bottom:14px;
    font-weight:600; font-size:14px;
    background:color-mix(in srgb,var(--naranja) 12%,var(--panel));
    border:1px solid color-mix(in srgb,var(--naranja) 35%,transparent);
    color:var(--naranja);
  }}
  .obsoleto.visible {{ display:flex; }}

  .metricas {{ display:grid; grid-template-columns:repeat({cols_metricas},1fr); gap:8px; padding:10px 0; border-top:1px solid var(--linea); border-bottom:1px solid var(--linea); }}
  .metricas div {{ display:flex; flex-direction:column; gap:1px; }}
  .metricas .k {{ font-size:10.5px; color:var(--suave); text-transform:uppercase; letter-spacing:.05em; }}
  .metricas .v {{ font-size:14px; font-weight:600; font-variant-numeric:tabular-nums; }}
  .metricas .v.bien {{ color:var(--verde); }}
  .metricas .v.alerta {{ color:var(--amarillo); }}
  .metricas .v.mal {{ color:var(--rojo); }}

  .historial {{ display:flex; gap:2px; margin:12px 0 10px; height:22px; align-items:stretch; }}
  .hx {{ flex:1; border-radius:2px; min-width:2px; }}
  .hx.arriba {{ background:var(--verde); }}
  .hx.lento {{ background:var(--amarillo); }}
  .hx.degradado {{ background:var(--naranja); }}
  .hx.caido {{ background:var(--rojo); }}
  .hx.vacio {{ background:var(--linea); opacity:.45; }}

  .sitio footer {{ display:flex; align-items:center; justify-content:space-between; gap:10px; }}
  .spark {{ width:150px; height:32px; }}
  .spark polyline {{ fill:none; stroke:var(--acento); stroke-width:1.6; stroke-linejoin:round; stroke-linecap:round; vector-effect:non-scaling-stroke; }}
  .nodata {{ font-size:11px; color:var(--suave); font-style:italic; }}
  .ip {{ font-size:11px; color:var(--suave); font-family:ui-monospace,SFMono-Regular,Menlo,monospace; text-align:right; word-break:break-all; }}

  /* ---------- Reporte de incidencias ---------- */
  .incidencias {{ margin-top:34px; padding-top:26px; border-top:1px solid var(--linea); }}
  .titulo-sec {{ display:flex; flex-wrap:wrap; gap:12px; align-items:center; justify-content:space-between; margin-bottom:12px; }}
  .titulo-sec h2 {{ margin:0; font-size:18px; font-weight:640; letter-spacing:-.01em; }}
  .periodo {{ margin:0 0 15px; font-size:12.5px; color:var(--suave); font-variant-numeric:tabular-nums; }}

  /* Pestañas de periodo */
  .tabs {{ display:inline-flex; gap:2px; background:color-mix(in srgb,var(--suave) 11%,transparent); padding:3px; border-radius:9px; }}
  .tab {{ appearance:none; border:0; background:transparent; cursor:pointer; padding:6px 14px; border-radius:6px; font:inherit; font-size:12.5px; font-weight:600; color:var(--suave); transition:background .15s ease,color .15s ease; }}
  .tab:hover {{ color:var(--texto); }}
  .tab.activa {{ background:var(--panel); color:var(--texto); box-shadow:var(--sombra); }}
  .tab:focus-visible {{ outline:2px solid var(--acento); outline-offset:1px; }}
  .panel.oculto {{ display:none; }}

  .patron {{ background:color-mix(in srgb,var(--naranja) 9%,var(--panel)); border:1px solid color-mix(in srgb,var(--naranja) 30%,transparent); border-radius:var(--radio); padding:15px 18px; margin-bottom:20px; }}
  .patron h4 {{ margin:0 0 7px; font-size:14px; font-weight:640; color:var(--naranja); }}
  .patron p {{ margin:0 0 10px; font-size:13px; line-height:1.55; color:var(--suave); }}
  .patron ul {{ margin:0; padding-left:19px; font-size:13px; }}
  .patron li {{ margin-bottom:3px; }}

  .graficas {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(360px,1fr)); gap:14px; margin-bottom:14px; }}
  figure {{ margin:0; min-width:0; background:var(--panel); border:1px solid var(--linea); border-radius:var(--radio); padding:15px 17px; box-shadow:var(--sombra); }}
  figure.ancha {{ margin-bottom:14px; }}
  figcaption {{ font-size:12px; font-weight:640; color:var(--suave); text-transform:uppercase; letter-spacing:.05em; margin-bottom:13px; }}
  .vacio {{ margin:0; font-size:13px; color:var(--suave); font-style:italic; }}

  /* El contenido ancho scrollea dentro de su propia caja: el cuerpo de la
     pagina nunca debe scrollear en horizontal. */
  .scrollable {{ overflow-x:auto; overflow-y:hidden; -webkit-overflow-scrolling:touch; }}

  /* Barras horizontales: una sola serie, la identidad va en la etiqueta */
  .barras {{ display:flex; flex-direction:column; gap:8px; }}
  .fila {{ display:grid; grid-template-columns:minmax(0,1.5fr) minmax(60px,2fr) auto; gap:10px; align-items:center; }}
  .etq {{ font-size:12.5px; line-height:1.3; color:var(--texto); overflow-wrap:anywhere; }}
  .pista {{ background:color-mix(in srgb,var(--suave) 15%,transparent); border-radius:4px; height:9px; overflow:hidden; }}
  .barra {{ display:block; height:100%; border-radius:0 4px 4px 0; transition:width .3s ease; }}
  .val {{ font-size:12px; font-weight:600; color:var(--suave); font-variant-numeric:tabular-nums; white-space:nowrap; }}
  /* La textura marca "esta barra se sale de la escala" sin depender del color */
  .fila.atipico .barra {{ background-image:repeating-linear-gradient(135deg,transparent 0 5px,rgba(255,255,255,.32) 5px 10px); }}
  .fila.atipico .val {{ color:var(--rojo); }}
  .nota-escala {{ margin:11px 0 0; font-size:11px; line-height:1.45; color:var(--suave); font-style:italic; }}

  /* Columnas por hora */
  .horas {{ display:flex; gap:3px; align-items:flex-end; height:104px; min-width:420px; }}
  .col {{ flex:1; display:flex; flex-direction:column; justify-content:flex-end; align-items:center; height:100%; gap:5px; }}
  .tallo {{ width:100%; background:var(--acento); border-radius:3px 3px 0 0; min-height:2px; }}
  .col.cero .tallo {{ background:color-mix(in srgb,var(--suave) 18%,transparent); height:2px!important; }}
  .hh {{ font-size:9.5px; color:var(--suave); font-variant-numeric:tabular-nums; }}

  /* Linea de tiempo de incidentes */
  .linea {{ list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:1px; }}
  .ev {{ display:grid; grid-template-columns:auto minmax(0,1.1fr) auto minmax(0,1.8fr); gap:11px; align-items:center; padding:8px 11px; border-radius:7px; border-left:3px solid var(--linea); font-size:12.5px; }}
  .ev:nth-child(odd) {{ background:color-mix(in srgb,var(--suave) 5%,transparent); }}
  .ev.caido {{ border-left-color:var(--rojo); }}
  .ev.degradado {{ border-left-color:var(--naranja); }}
  .ev.lento {{ border-left-color:var(--amarillo); }}
  .cuando {{ color:var(--suave); font-variant-numeric:tabular-nums; white-space:nowrap; }}
  .quien {{ font-weight:600; color:var(--texto); }}
  .dur {{ font-weight:600; font-variant-numeric:tabular-nums; white-space:nowrap; }}
  .ev.caido .dur {{ color:var(--rojo); }}
  .ev.degradado .dur {{ color:var(--naranja); }}
  .ev.lento .dur {{ color:var(--amarillo); }}
  .ev.abierto .dur::after {{ content:" ●"; }}
  .pormenor {{ color:var(--suave); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}

  .pie {{ margin-top:26px; padding-top:16px; border-top:1px solid var(--linea); font-size:12px; color:var(--suave); display:flex; flex-wrap:wrap; gap:14px; justify-content:space-between; }}

  @media (max-width:760px) {{
    .ev {{ grid-template-columns:auto 1fr; row-gap:2px; }}
    .ev .dur {{ grid-column:2; }}
    .ev .pormenor {{ grid-column:1/-1; white-space:normal; }}
    .fila {{ grid-template-columns:minmax(0,1fr) minmax(50px,1.4fr) auto; }}
  }}

  @media (max-width:640px) {{
    body {{ padding:14px; }}
    .rejilla, .graficas {{ grid-template-columns:1fr; }}
    .titulo-sec {{ flex-direction:column; gap:4px; }}
  }}
</style>
</head>
<body>
<div class="wrap">

  <div class="cabeza">
    <h1>Monitoreo — {html.escape(cliente)}</h1>
    <span class="meta">Última revisión: {ahora} <span id="hace"></span></span>
  </div>

  <div class="obsoleto" id="obsoleto">
    <span>⚠️</span>
    <span id="obsoleto-txt"></span>
  </div>

  <div class="banner {banner_clase}">
    <span class="pt"></span>
    <span>{banner_txt}</span>
  </div>

  <section class="resumen">
    <div class="kpi"><div class="n">{total}</div><div class="l">Sitios</div></div>
    <div class="kpi arriba"><div class="n">{conteo['arriba']}</div><div class="l">En línea</div></div>
    <div class="kpi lento"><div class="n">{conteo['lento']}</div><div class="l">Lentos</div></div>
    <div class="kpi degradado"><div class="n">{conteo['degradado']}</div><div class="l">Degradados</div></div>
    <div class="kpi caido"><div class="n">{conteo['caido']}</div><div class="l">Caídos</div></div>
  </section>

  <section class="rejilla">
{tarjetas}
  </section>
{incidencias_html}
  <div class="pie">
    <span>Generado por el monitor DTS · {n_hist} sitios con historial</span>
    <span>Digital Transformation Services</span>
  </div>

</div>

<script>
// Un dashboard de disponibilidad que muestra datos viejos sin avisar es peor
// que no tener dashboard: afirma que todo esta bien cuando en realidad nadie
// esta midiendo. Aqui se compara la marca de generacion contra el reloj del
// visitante y se avisa en cuanto los datos dejan de ser confiables.
(function () {{
  var GENERADO = new Date("{generado_iso}");
  var UMBRAL_MIN = 5;

  function texto(min) {{
    if (min < 1) return "hace unos segundos";
    if (min < 60) return "hace " + min + " min";
    var h = Math.floor(min / 60);
    if (h < 24) return "hace " + h + (h === 1 ? " hora" : " horas");
    var d = Math.floor(h / 24);
    return "hace " + d + (d === 1 ? " día" : " días");
  }}

  function pintar() {{
    var min = Math.floor((Date.now() - GENERADO.getTime()) / 60000);
    if (min < 0) min = 0;

    var hace = document.getElementById("hace");
    if (hace) hace.textContent = "(" + texto(min) + ")";

    var caja = document.getElementById("obsoleto");
    var txt = document.getElementById("obsoleto-txt");
    if (!caja || !txt) return;

    if (min >= UMBRAL_MIN) {{
      txt.textContent =
        "Estos datos se generaron " + texto(min) + " y el monitor deberia " +
        "actualizarlos cada minuto. El estado que ves abajo puede ya no ser real.";
      caja.classList.add("visible");
    }} else {{
      caja.classList.remove("visible");
    }}
  }}

  pintar();
  setInterval(pintar, 30000);
}})();

// Pestañas del reporte de incidencias. Los tres periodos ya vienen en el
// HTML: aqui solo se alterna cual se muestra. Sin peticiones, sin servidor,
// funciona igual embebido en WordPress que abierto como archivo suelto.
(function () {{
  var tabs = [].slice.call(document.querySelectorAll(".incidencias .tab"));
  var paneles = [].slice.call(document.querySelectorAll(".incidencias .panel"));
  if (!tabs.length) return;

  function activar(clave, foco) {{
    tabs.forEach(function (t) {{
      var on = t.getAttribute("data-periodo") === clave;
      t.classList.toggle("activa", on);
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
      if (on && foco) t.focus();
    }});
    paneles.forEach(function (p) {{
      p.classList.toggle("oculto", p.getAttribute("data-periodo") !== clave);
    }});
    try {{ localStorage.setItem("dts-periodo", clave); }} catch (e) {{}}
  }}

  tabs.forEach(function (t, i) {{
    t.addEventListener("click", function () {{
      activar(t.getAttribute("data-periodo"));
    }});
    // Flechas para moverse entre pestañas, como espera un lector de pantalla.
    t.addEventListener("keydown", function (e) {{
      var d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      if (!d) return;
      e.preventDefault();
      var sig = tabs[(i + d + tabs.length) % tabs.length];
      activar(sig.getAttribute("data-periodo"), true);
    }});
  }});

  // Recordar el periodo que el usuario venia viendo.
  try {{
    var guardado = localStorage.getItem("dts-periodo");
    if (guardado && document.querySelector('.panel[data-periodo="' + guardado + '"]')) {{
      activar(guardado);
    }}
  }} catch (e) {{}}
}})();
</script>
</body>
</html>
"""
    salida.write_text(doc, encoding="utf-8")
    return salida


# ------------------------------------------------------- reporte de incidencias

def _barras_horizontales(datos, unidad="", color="var(--rojo)", max_filas=12,
                         formato=None):
    """Barras horizontales para comparar magnitud entre sitios.

    Una sola serie: el color no codifica identidad, solo dibuja la barra.
    Por eso no hay leyenda ni problema de separacion para daltonismo — la
    identidad la lleva la etiqueta de texto, que siempre esta.

    Cuando un valor aplasta a los demas (un sitio caido tres dias contra
    otros caidos tres minutos) la escala lineal vuelve invisible al resto.
    En ese caso la barra dominante se marca aparte y la escala se calcula
    sobre los demas, para que sigan siendo comparables entre si. El valor
    real siempre se imprime al lado: la escala ayuda a comparar, el numero
    es el que informa.
    """
    if not datos:
        return '<p class="vacio">Sin datos en el periodo.</p>'

    fmt = formato or (lambda v: f"{v}{unidad}")
    filas = sorted(datos.items(), key=lambda x: -x[1])[:max_filas]
    valores = [v for _, v in filas]
    tope = max(valores) or 1

    # ¿Hay un valor atipico que se come la escala?
    resto = sorted(valores)[:-1]
    mediana_resto = resto[len(resto) // 2] if resto else 0
    hay_atipico = bool(resto) and mediana_resto > 0 and tope >= mediana_resto * 12
    escala = max(resto) if hay_atipico and resto else tope

    salida = ['<div class="barras">']
    for etiqueta, valor in filas:
        fuera = hay_atipico and valor > escala
        pct = 100 if fuera else max(2, 100 * valor / (escala or 1))
        texto = fmt(valor)
        salida.append(
            f'<div class="fila{" atipico" if fuera else ""}" '
            f'title="{html.escape(etiqueta)}: {html.escape(texto)}">'
            f'<span class="etq">{html.escape(etiqueta)}</span>'
            f'<span class="pista"><span class="barra" style="width:{pct:.1f}%;'
            f'background:{color}"></span></span>'
            f'<span class="val">{html.escape(texto)}</span>'
            f"</div>"
        )
    salida.append("</div>")
    if hay_atipico:
        salida.append(
            '<p class="nota-escala">La barra rayada excede la escala del resto. '
            "Se marca aparte para que los valores pequeños sigan siendo "
            "comparables entre sí.</p>"
        )
    return "".join(salida)


def _columnas_hora(por_hora):
    """Incidentes por hora del dia. Delata si las caidas se concentran."""
    if not por_hora:
        return '<p class="vacio">Sin datos en el periodo.</p>'

    tope = max(por_hora.values()) or 1
    salida = ['<div class="horas">']
    for h in range(24):
        n = por_hora.get(h, 0)
        alto = (n / tope) * 100 if n else 0
        clase = "col" + (" cero" if not n else "")
        titulo = f"{h:02d}:00 — {n} incidente{'s' if n != 1 else ''}"
        salida.append(
            f'<div class="{clase}" title="{titulo}">'
            f'<span class="tallo" style="height:{alto:.0f}%"></span>'
            f'<span class="hh">{h:02d}</span>'
            f"</div>"
        )
    salida.append("</div>")
    return "".join(salida)


def _linea_tiempo(incidentes, publico, limite=10):
    if not incidentes:
        return '<p class="vacio">Sin incidentes registrados en el periodo. 🎉</p>'

    import incidencias as inc
    salida = ['<ol class="linea">']
    for i in incidentes[:limite]:
        est = i["estado"]
        dur = "en curso" if i["abierto"] else inc.duracion_humana(i["minutos"])
        causa = "" if publico else html.escape(i.get("causa", "")[:70])
        abierto = " abierto" if i["abierto"] else ""
        salida.append(
            f'<li class="ev {est}{abierto}">'
            f'<span class="cuando">{i["inicio"]:%d/%m %H:%M}</span>'
            f'<span class="quien">{html.escape(i["sitio"])}</span>'
            f'<span class="dur">{html.escape(dur)}</span>'
            + (f'<span class="pormenor">{causa}</span>' if causa else "")
            + "</li>"
        )
    salida.append("</ol>")
    return "".join(salida)


PERIODOS = [
    ("dia",    "24 horas",  1),
    ("semana", "7 días",    7),
    ("mes",    "30 días",  30),
]


def seccion_incidencias(publico=False, historial_path=HISTORIAL):
    """Reporte con pestañas de dia, semana y mes.

    Los tres paneles se generan de una vez y se alternan con CSS: la pagina
    es estatica y vive tambien dentro de WordPress, donde no hay servidor
    que responda a un cambio de periodo.
    """
    try:
        import incidencias as inc
    except ImportError:
        return ""

    pestanas, paneles = [], []
    hubo_datos = False

    for i, (clave, etiqueta, dias) in enumerate(PERIODOS):
        try:
            lista, res = inc.analizar(historial_path, dias)
        except Exception:
            continue
        if not res.get("revisiones"):
            continue
        hubo_datos = True
        activa = " activa" if not pestanas else ""
        pestanas.append(
            f'<button type="button" class="tab{activa}" role="tab" '
            f'id="tab-{clave}" aria-controls="panel-{clave}" '
            f'aria-selected="{"true" if activa else "false"}" '
            f'data-periodo="{clave}">{etiqueta}</button>'
        )
        paneles.append(
            f'<div class="panel{"" if activa else " oculto"}" role="tabpanel" '
            f'id="panel-{clave}" aria-labelledby="tab-{clave}" '
            f'data-periodo="{clave}">{_panel_periodo(inc, lista, res, publico, dias)}</div>'
        )

    if not hubo_datos:
        return ""

    return f"""
  <section class="incidencias">
    <div class="titulo-sec">
      <h2>Reporte de incidencias</h2>
      <div class="tabs" role="tablist" aria-label="Periodo del reporte">
        {''.join(pestanas)}
      </div>
    </div>
    {''.join(paneles)}
  </section>"""


def _panel_periodo(inc, lista, res, publico, dias_pedidos):
    disp = res["disponibilidad"]
    clase_disp = "bien" if disp >= 99.5 else ("alerta" if disp >= 97 else "mal")

    periodo = ""
    cobertura = ""
    if res["desde"] and res["hasta"]:
        periodo = f"{res['desde']:%d/%m} – {res['hasta']:%d/%m}"
        # El monitoreo empezo hace poco: decirlo, porque si no un periodo de
        # 30 dias que en realidad cubre 3 se lee como si fueran 30.
        reales = (res["hasta"] - res["desde"]).total_seconds() / 86400
        if reales < dias_pedidos * 0.9:
            n = max(1, round(reales))
            cobertura = (f' · <b>solo hay {n} día{"s" if n != 1 else ""} '
                         f"de historial</b>")

    # Aviso de caidas simultaneas: varios sitios cayendo dentro de la misma
    # ventana casi nunca son fallas independientes.
    aviso = ""
    if res["simultaneos"]:
        lineas = []
        for cuando, sitios in res["simultaneos"]:
            lineas.append(
                f"<li><b>{cuando:%d/%m %H:%M}</b> — {len(sitios)} sitios: "
                f"{html.escape(', '.join(sorted(sitios)))}</li>"
            )
        aviso = f"""
      <div class="patron">
        <h4>⚠️ Caídas simultáneas detectadas</h4>
        <p>Tres o más sitios fallaron dentro de la misma ventana de 10 minutos.
           Eso rara vez son fallas independientes: apunta a infraestructura
           compartida — saturación del servidor, límite de recursos o un reinicio.</p>
        <ul>{''.join(lineas)}</ul>
      </div>"""

    return f"""
    <p class="periodo">{periodo} · {res['revisiones']:,} revisiones{cobertura}</p>

    <section class="resumen">
      <div class="kpi"><div class="n {clase_disp}">{disp}%</div><div class="l">Disponibilidad</div></div>
      <div class="kpi"><div class="n">{res['incidentes']}</div><div class="l">Incidentes</div></div>
      <div class="kpi"><div class="n">{res['sitios_afectados']}</div><div class="l">Sitios afectados</div></div>
      <div class="kpi"><div class="n">{inc.duracion_humana(res['minutos_sin_servicio'])}</div><div class="l">Sin servicio</div></div>
      <div class="kpi"><div class="n">{inc.duracion_humana(res['mttr'])}</div><div class="l">Recuperación media</div></div>
    </section>
    {aviso}

    <div class="graficas">
      <figure>
        <figcaption>Incidentes por sitio</figcaption>
        {_barras_horizontales(res['incidentes_por_sitio'])}
      </figure>

      <figure>
        <figcaption>Tiempo sin servicio por sitio</figcaption>
        {_barras_horizontales(res['minutos_por_sitio'], formato=inc.duracion_humana)}
      </figure>
    </div>

    <figure class="ancha">
      <figcaption>Incidentes por hora del día</figcaption>
      <div class="scrollable">{_columnas_hora(res['por_hora'])}</div>
    </figure>

    <figure class="ancha">
      <figcaption>Últimos incidentes{f' · {min(10, len(lista))} de {len(lista)}' if len(lista) > 10 else ''}</figcaption>
      {_linea_tiempo(lista, publico, 10)}
    </figure>"""


def generar_ambos(cliente, resultados=None, historial_path=HISTORIAL):
    """Genera la version interna (completa) y la publica (sin infraestructura)."""
    interno = generar(cliente, resultados, historial_path, SALIDA, publico=False)
    publico = generar(cliente, resultados, historial_path,
                      BASE / "dashboard-publico.html", publico=True)
    return interno, publico


if __name__ == "__main__":
    cfg = json.loads((BASE / "sitios.json").read_text(encoding="utf-8"))
    for p in generar_ambos(cfg["cliente"]):
        print(p)
