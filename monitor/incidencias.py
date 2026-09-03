#!/usr/bin/env python3
"""
Reconstruye incidentes a partir del historial de revisiones.

El historial es una lista de mediciones sueltas. Lo que le sirve a una
persona no es "4,787 revisiones en estado caido" sino "La Isla Acapulco
lleva 3 dias sin servicio, en un solo incidente". Este modulo convierte
lo primero en lo segundo.

Un incidente es un periodo continuo en el que un sitio no estuvo `arriba`.
Empieza en la primera revision degradada y termina en la primera revision
sana posterior. Si no hay revision sana posterior, sigue abierto.
"""

import json
import datetime
from pathlib import Path
from collections import defaultdict

BASE = Path(__file__).resolve().parent
HISTORIAL = BASE / "historial.jsonl"

SANO = "arriba"
FORMATO = "%Y-%m-%d %H:%M"

# Un solo minuto raro no es un incidente: los sitios parpadean. Se exige
# que la anomalia persista para no llenar el reporte de ruido.
MIN_REVISIONES = 2


def _fecha(texto):
    try:
        return datetime.datetime.strptime(texto, FORMATO)
    except (ValueError, TypeError):
        return None


def cargar(ruta=HISTORIAL, dias=7):
    """Lee el historial agrupado por sitio, en orden cronologico."""
    if not ruta.exists():
        return {}

    corte = datetime.datetime.now() - datetime.timedelta(days=dias)
    por_sitio = defaultdict(list)

    with ruta.open(encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea:
                continue
            try:
                r = json.loads(linea)
            except json.JSONDecodeError:
                continue
            cuando = _fecha(r.get("momento"))
            if not cuando or cuando < corte:
                continue
            r["_t"] = cuando
            por_sitio[r.get("nombre", "?")].append(r)

    for registros in por_sitio.values():
        registros.sort(key=lambda x: x["_t"])
    return dict(por_sitio)


def detectar(por_sitio):
    """Convierte las mediciones en una lista de incidentes."""
    incidentes = []

    for nombre, registros in por_sitio.items():
        abierto = None

        for r in registros:
            estado = r.get("estado", SANO)

            if estado != SANO:
                if abierto is None:
                    abierto = {
                        "sitio": nombre,
                        "host": r.get("host", ""),
                        "inicio": r["_t"],
                        "fin": None,
                        "estado": estado,
                        "revisiones": 1,
                        "causas": [r.get("detalle", "")],
                    }
                else:
                    abierto["revisiones"] += 1
                    detalle = r.get("detalle", "")
                    if detalle and detalle not in abierto["causas"]:
                        abierto["causas"].append(detalle)
                    # El peor estado observado manda.
                    orden = {"lento": 1, "degradado": 2, "caido": 3}
                    if orden.get(estado, 0) > orden.get(abierto["estado"], 0):
                        abierto["estado"] = estado
            elif abierto is not None:
                abierto["fin"] = r["_t"]
                if abierto["revisiones"] >= MIN_REVISIONES:
                    incidentes.append(abierto)
                abierto = None

        # Incidente que sigue vivo al final del historial.
        if abierto is not None and abierto["revisiones"] >= MIN_REVISIONES:
            incidentes.append(abierto)

    for i in incidentes:
        fin = i["fin"] or datetime.datetime.now()
        i["minutos"] = max(1, int((fin - i["inicio"]).total_seconds() / 60))
        i["abierto"] = i["fin"] is None
        i["causa"] = i["causas"][0] if i["causas"] else ""

    incidentes.sort(key=lambda x: x["inicio"], reverse=True)
    return incidentes


def resumir(por_sitio, incidentes):
    """Metricas de cabecera del reporte."""
    total = sum(len(v) for v in por_sitio.values())
    sanas = sum(
        1 for v in por_sitio.values() for r in v if r.get("estado") == SANO
    )
    disponibilidad = round(100 * sanas / total, 2) if total else 0.0

    cerrados = [i for i in incidentes if not i["abierto"]]
    mttr = round(sum(i["minutos"] for i in cerrados) / len(cerrados)) if cerrados else 0

    # Uptime por sitio
    por_sitio_uptime = {}
    for nombre, registros in por_sitio.items():
        if not registros:
            continue
        ok = sum(1 for r in registros if r.get("estado") == SANO)
        por_sitio_uptime[nombre] = round(100 * ok / len(registros), 2)

    # Minutos sin servicio por sitio
    minutos_por_sitio = defaultdict(int)
    incidentes_por_sitio = defaultdict(int)
    for i in incidentes:
        minutos_por_sitio[i["sitio"]] += i["minutos"]
        incidentes_por_sitio[i["sitio"]] += 1

    # Distribucion por hora del dia: revela si las caidas se concentran
    # en alguna franja, que suele delatar saturacion o tareas programadas.
    por_hora = defaultdict(int)
    for i in incidentes:
        por_hora[i["inicio"].hour] += 1

    # Incidentes simultaneos: varios sitios cayendo en la misma ventana
    # casi nunca son fallas independientes, son infraestructura compartida.
    ventanas = defaultdict(set)
    for i in incidentes:
        clave = i["inicio"].replace(minute=(i["inicio"].minute // 10) * 10)
        ventanas[clave].add(i["sitio"])
    simultaneos = sorted(
        ((k, v) for k, v in ventanas.items() if len(v) >= 3),
        key=lambda x: x[0], reverse=True,
    )

    momentos = [r["_t"] for v in por_sitio.values() for r in v]

    return {
        "revisiones": total,
        "disponibilidad": disponibilidad,
        "incidentes": len(incidentes),
        "abiertos": sum(1 for i in incidentes if i["abierto"]),
        "sitios_afectados": len({i["sitio"] for i in incidentes}),
        "minutos_sin_servicio": sum(i["minutos"] for i in incidentes),
        "mttr": mttr,
        "uptime_por_sitio": por_sitio_uptime,
        "minutos_por_sitio": dict(minutos_por_sitio),
        "incidentes_por_sitio": dict(incidentes_por_sitio),
        "por_hora": dict(por_hora),
        "simultaneos": simultaneos[:5],
        "desde": min(momentos) if momentos else None,
        "hasta": max(momentos) if momentos else None,
    }


def analizar(ruta=HISTORIAL, dias=7):
    por_sitio = cargar(ruta, dias)
    incidentes = detectar(por_sitio)
    return incidentes, resumir(por_sitio, incidentes)


def duracion_humana(minutos):
    if minutos < 60:
        return f"{minutos} min"
    horas = minutos / 60
    if horas < 24:
        h, m = divmod(minutos, 60)
        return f"{h} h {m} min" if m else f"{h} h"
    dias = minutos / 1440
    d = int(dias)
    h = int((minutos - d * 1440) / 60)
    return f"{d} d {h} h" if h else f"{d} d"


if __name__ == "__main__":
    incidentes, resumen = analizar()
    print(f"Revisiones:        {resumen['revisiones']:,}")
    print(f"Disponibilidad:    {resumen['disponibilidad']}%")
    print(f"Incidentes:        {resumen['incidentes']} ({resumen['abiertos']} abiertos)")
    print(f"Sitios afectados:  {resumen['sitios_afectados']}")
    print(f"Sin servicio:      {duracion_humana(resumen['minutos_sin_servicio'])}")
    print(f"MTTR:              {duracion_humana(resumen['mttr'])}")
    print()
    print("Incidentes por sitio:")
    for s, n in sorted(resumen["incidentes_por_sitio"].items(),
                       key=lambda x: -x[1]):
        mins = resumen["minutos_por_sitio"].get(s, 0)
        print(f"  {s:<24} {n:>3} incidentes · {duracion_humana(mins)}")
    print()
    if resumen["simultaneos"]:
        print("Caidas simultaneas (3+ sitios en 10 min):")
        for cuando, sitios in resumen["simultaneos"]:
            print(f"  {cuando:%d/%m %H:%M} — {len(sitios)}: {', '.join(sorted(sitios))}")
    print()
    print("Ultimos 10 incidentes:")
    for i in incidentes[:10]:
        estado = "ABIERTO" if i["abierto"] else duracion_humana(i["minutos"])
        print(f"  {i['inicio']:%d/%m %H:%M}  {i['sitio']:<22} {estado:<12} {i['causa'][:45]}")
