@echo off
REM Ejecutado cada minuto por la tarea programada "DTS Monitor GICSA".
REM Llama a WSL: si Ubuntu esta apagada, este comando la enciende sola.
REM Por eso la tarea vive en Windows y no en un cron de Linux.

wsl -d Ubuntu-24.04 -- /home/jairguzman/dts-venv/bin/python /mnt/c/Obsidian/dts-tools/monitor/monitor.py --dashboard --publicar >> "%~dp0run.log" 2>&1

REM El log se recorta para que no crezca sin control.
powershell -NoProfile -Command "$f='%~dp0run.log'; if ((Get-Item $f -EA SilentlyContinue).Length -gt 2MB) { Get-Content $f -Tail 500 | Set-Content \"$f.tmp\"; Move-Item \"$f.tmp\" $f -Force }"
