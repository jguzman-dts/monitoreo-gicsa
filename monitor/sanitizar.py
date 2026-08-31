#!/usr/bin/env python3
"""
Quita del historial los campos de infraestructura del cliente.

Se corre una sola vez, antes de versionar un historial que se acumulo
localmente cuando todavia guardaba IPs. De ahi en adelante el monitor ya
no las escribe por defecto.
"""

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
HISTORIAL = BASE / "historial.jsonl"
QUITAR = {"ips", "url_final", "titulo"}

if not HISTORIAL.exists():
    raise SystemExit("No hay historial que limpiar.")

lineas, tocadas = [], 0
for linea in HISTORIAL.read_text(encoding="utf-8").splitlines():
    linea = linea.strip()
    if not linea:
        continue
    try:
        r = json.loads(linea)
    except json.JSONDecodeError:
        continue
    if QUITAR & r.keys():
        tocadas += 1
        r = {k: v for k, v in r.items() if k not in QUITAR}
    lineas.append(json.dumps(r, ensure_ascii=False))

HISTORIAL.write_text("\n".join(lineas) + "\n", encoding="utf-8")
print(f"{len(lineas)} registros · {tocadas} sanitizados")
