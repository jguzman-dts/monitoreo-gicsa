#!/usr/bin/env python3
"""Genera el bloque HTML listo para pegar en una pagina de WordPress."""
from pathlib import Path
import publicar

BASE = Path(__file__).resolve().parent
origen = BASE / "dashboard-publico.html"
destino = BASE / "bloque-wp.html"

contenido = publicar.envolver(origen.read_text(encoding="utf-8"))
destino.write_text(contenido, encoding="utf-8")
print(f"{destino} — {len(contenido)} bytes")
