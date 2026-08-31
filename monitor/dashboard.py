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


def barra_historial(registros, maximo=40):
    """Franja de cuadritos con el historial reciente, estilo status page."""
    recientes = registros[-maximo:]
    faltan = maximo - len(recientes)
    celdas = ['<i class="hx vacio"></i>'] * faltan
    for r in recientes:
        est = r.get("estado", "caido")
        momento = html.escape(r.get("momento", ""))
        detalle = html.escape(r.get("detalle", "")[:70])
        celdas.append(
            f'<i class="hx {est}" title="{momento} — {detalle}"></i>'
        )
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


def generar(cliente, resultados=None, historial_path=HISTORIAL, salida=SALIDA):
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
        ips = ", ".join(r.get("ips", [])) or "—"

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

        <p class="detalle">{html.escape(r.get('detalle', ''))}</p>

        <div class="metricas">
          <div><span class="k">Respuesta</span><span class="v">{tiempo}</span></div>
          <div><span class="k">Uptime</span><span class="v">{up if up is not None else '—'}{'%' if up is not None else ''}</span></div>
          <div><span class="k">SSL</span><span class="v {ssl_clase}">{ssl_txt}</span></div>
        </div>

        <div class="historial" title="Historial de revisiones, la más reciente a la derecha">
          {barra_historial(registros)}
        </div>

        <footer>
          {sparkline(registros)}
          <span class="ip">{html.escape(ips)}</span>
        </footer>
      </article>""")

    return _escribir(
        salida, cliente, ahora, total, conteo, banner_clase, banner_txt,
        "\n".join(tarjetas), len(hist)
    )


def _escribir(salida, cliente, ahora, total, conteo, banner_clase, banner_txt, tarjetas, n_hist):
    doc = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
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

  .detalle {{ margin:0 0 12px; font-size:13px; color:var(--suave); min-height:2.6em; }}

  .metricas {{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; padding:10px 0; border-top:1px solid var(--linea); border-bottom:1px solid var(--linea); }}
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

  .pie {{ margin-top:26px; padding-top:16px; border-top:1px solid var(--linea); font-size:12px; color:var(--suave); display:flex; flex-wrap:wrap; gap:14px; justify-content:space-between; }}

  @media (max-width:640px) {{
    body {{ padding:14px; }}
    .rejilla {{ grid-template-columns:1fr; }}
  }}
</style>
</head>
<body>
<div class="wrap">

  <div class="cabeza">
    <h1>Monitoreo — {html.escape(cliente)}</h1>
    <span class="meta">Última revisión: {ahora}</span>
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

  <div class="pie">
    <span>Generado por el monitor DTS · {n_hist} sitios con historial</span>
    <span>Digital Transformation Services</span>
  </div>

</div>
</body>
</html>
"""
    salida.write_text(doc, encoding="utf-8")
    return salida


if __name__ == "__main__":
    cfg = json.loads((BASE / "sitios.json").read_text(encoding="utf-8"))
    print(generar(cfg["cliente"]))
