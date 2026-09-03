#!/usr/bin/env python3
"""Renderiza solo el reporte de incidencias, para revisarlo aislado."""
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent
origen = (BASE / "dashboard.html").read_text(encoding="utf-8")

estilo = re.search(r"<style>.*?</style>", origen, re.S).group(0)
seccion = re.search(r'<section class="incidencias">.*?</section>\s*(?=<div class="pie">)',
                    origen, re.S).group(0)

salida = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reporte de incidencias — vista aislada</title>
{estilo}
<style>.incidencias{{margin-top:0;padding-top:0;border-top:none}}</style>
</head><body><div class="wrap">{seccion}</div></body></html>
"""
destino = BASE / "vista-incidencias.html"
destino.write_text(salida, encoding="utf-8")
print(f"{destino} — {len(salida)} bytes")
