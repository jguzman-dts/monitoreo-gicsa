#!/usr/bin/env python3
"""Valida que el workflow de GitHub Actions sea YAML correcto.

GitHub ignora en silencio los workflows con sintaxis invalida: no aparecen
en la pestana Actions y no dan ningun error visible. Por eso conviene
validarlos antes de subirlos.
"""
import sys
from pathlib import Path

RUTA = Path("/mnt/c/Obsidian/dts-tools/.github/workflows/monitor.yml")

try:
    import yaml
except ImportError:
    sys.exit("Falta pyyaml: ~/dts-venv/bin/pip install pyyaml")

if not RUTA.exists():
    sys.exit(f"No existe {RUTA}")

texto = RUTA.read_text(encoding="utf-8")

try:
    d = yaml.safe_load(texto)
except yaml.YAMLError as e:
    sys.exit(f"YAML INVALIDO:\n{e}")

print("YAML valido")
print("  bytes:", len(texto))
# 'on' en YAML 1.1 se interpreta como el booleano True: por eso se busca
# con las dos llaves.
disparadores = d.get("on", d.get(True))
print("  claves raiz:", list(d.keys()))
print("  triggers:", list(disparadores.keys()) if isinstance(disparadores, dict) else disparadores)
print("  jobs:", list(d.get("jobs", {}).keys()))

job = next(iter(d.get("jobs", {}).values()), {})
print("  pasos:", len(job.get("steps", [])))
print("  runs-on:", job.get("runs-on"))

# Secretos que el workflow espera
import re
secretos = sorted(set(re.findall(r"secrets\.([A-Z_]+)", texto)))
print("  secretos requeridos:", ", ".join(secretos) or "ninguno")
