# dts-tools

Herramientas internas de DTS que corren en WSL2 (Ubuntu 24.04) sobre el equipo `DIGITALDTS`.

Vive **fuera** del vault de Obsidian a propósito: el vault es para notas, no para código.

```
C:\Obsidian\
├── DTSLOCAL\      ← vault de Obsidian (segundo cerebro)
└── dts-tools\     ← esto
    ├── auditor\   ← auditor de sitios de clientes
    └── n8n\       ← automatizaciones
```

Desde WSL2 esta carpeta es `/mnt/c/Obsidian/dts-tools`.

---

## 1. Auditor de sitios

Audita los sitios de los clientes y escribe un reporte por cliente en
`20-Clientes/Auditorias/` del vault, con los hallazgos como pendientes en
checkbox para que la tarea diaria de la 1 PM los recoja.

### Qué revisa

| | |
|---|---|
| **DNS** | Que el dominio resuelva, y a qué IPs |
| **www vs apex** | Si una variante funciona y la otra no, hay tráfico perdiéndose |
| **SSL** | Fecha de vencimiento, emisor, alerta a 30 días |
| **Respuesta** | Código HTTP, cadena de redirecciones, tiempo de carga, peso |
| **Dominio estacionado** | Detecta páginas de "parking" y de venta de dominios |
| **SEO** | Title, meta description, H1, canonical, Open Graph, viewport, alt en imágenes |
| **Frescura** | Fecha más reciente publicada — delata blogs abandonados |
| **Enlaces** | Muestrea hasta 25 enlaces y reporta los rotos |
| **Técnicos** | `robots.txt` y `sitemap.xml` |

### Instalación (una sola vez)

```
sudo apt install -y python3-venv && python3 -m venv ~/dts-venv && ~/dts-venv/bin/pip install requests beautifulsoup4
```

Ubuntu 24.04 no deja instalar paquetes de Python en el sistema (PEP 668), por eso
va en un entorno virtual en `~/dts-venv`.

### Uso

```
~/dts-venv/bin/python /mnt/c/Obsidian/dts-tools/auditor/auditor.py
```

| Variante | Qué hace |
|---|---|
| *(sin argumentos)* | Audita todos los clientes que tengan `sitio_web` |
| `"Class Education"` | Audita solo ese cliente |
| `--dry-run` | Muestra el resultado en pantalla sin escribir en el vault |

### Cómo sabe qué auditar

Lee `20-Clientes/*.md` del vault y toma el campo `sitio_web` del frontmatter.
Un cliente sin ese campo se omite y se reporta al final.

```yaml
---
tipo: cliente
nombre: "Class Education"
sitio_web: https://classeducation.com
---
```

---

## 1b. Monitor de disponibilidad

Vigila los sitios de `monitor/sitios.json`, detecta caidas y las registra en
una bitacora del vault. **Solo escribe cuando algo cambia**: un sitio estable
no genera ruido.

### Estados

| | Estado | Significa |
|---|---|---|
| 🟢 | `arriba` | Responde 200 en menos de 4 s |
| 🟡 | `lento` | Responde bien pero tarda mas de 4 s |
| 🟠 | `degradado` | HTTP 4xx, pagina casi vacia, o dominio estacionado |
| 🔴 | `caido` | DNS no resuelve, timeout, SSL invalido o HTTP 5xx |

### Uso

```
cd /mnt/c/Obsidian/dts-tools/monitor && ~/dts-venv/bin/python monitor.py --dashboard
```

| Variante | Que hace |
|---|---|
| *(sin argumentos)* | Revisa y actualiza la bitacora |
| `--once` | Revisa y muestra en pantalla, no escribe |
| `--dashboard` | Ademas regenera `dashboard.html` |

### Archivos que genera

| Archivo | Contenido |
|---|---|
| `estado.json` | Ultimo estado de cada sitio, para comparar y detectar cambios |
| `historial.jsonl` | Una linea por revision. Alimenta uptime y graficas |
| `dashboard.html` | Dashboard autocontenido |
| Bitacora en el vault | `20-Clientes/Monitoreo/<Cliente> — Bitacora de monitoreo.md` |

### Diagnostico manual

Cuando el monitor marca algo caido, `diagnostico.sh` profundiza: compara www
contra apex, https contra http, repite 3 veces y muestra cabeceras.

```
bash /mnt/c/Obsidian/dts-tools/monitor/diagnostico.sh gicsa.com.mx
```

### Servir el dashboard localmente

```
python3 -m http.server 8099 --bind 127.0.0.1 --directory /mnt/c/Obsidian/dts-tools/monitor
```

Queda en <http://127.0.0.1:8099/dashboard.html>.

### Automatizar (ya configurado)

La tarea de Windows `DTS Monitor GICSA` corre **cada minuto**.

Se ejecuta a traves de `run-silencioso.vbs`, no directo sobre `run.cmd`.
La opcion "Hidden" de una tarea programada solo la oculta en la interfaz
del Programador de tareas: **no suprime la consola del proceso**. Sin esa
capa, cada minuto parpadeaba una ventana de cmd en pantalla.

```
wscript.exe //nologo C:Obsidiandts-toolsmonitorun-silencioso.vbs
```

| Accion | Comando (PowerShell) |
|---|---|
| Ver estado | `Get-ScheduledTask "DTS Monitor GICSA" | Get-ScheduledTaskInfo` |
| Correr ahora | `Start-ScheduledTask "DTS Monitor GICSA"` |
| Desactivar | `Disable-ScheduledTask "DTS Monitor GICSA"` |
| Eliminar | `schtasks /delete /tn "DTS Monitor GICSA" /f` |

Se usa una tarea de Windows y no un cron dentro de WSL porque la tarea
**enciende WSL sola si esta apagada**; un cron de Linux muere con la distro.

### Reporte de incidencias

El dashboard incluye un reporte con tres periodos —**24 horas, 7 dias y
30 dias**— que se alternan con pestanas. Los tres se generan de una vez y
se alternan con CSS: la pagina es estatica y vive tambien dentro de
WordPress, donde no hay servidor que responda a un cambio de periodo.

Cuando el historial es mas corto que el periodo elegido, el panel lo
declara ("solo hay 3 dias de historial"). Un reporte de 30 dias que en
realidad cubre 3 se lee como si fueran 30.

`incidencias.py` reconstruye los incidentes desde las mediciones sueltas:
un incidente es un periodo continuo fuera de estado sano, y se exigen al
menos 2 revisiones consecutivas para no registrar parpadeos.


Desde **PowerShell de Windows**, no desde Ubuntu. Una tarea de Windows funciona
aunque WSL este apagada: la enciende sola. Un cron dentro de WSL no, porque
muere con la distro.

```
```

---

## 2. n8n — automatizaciones

Motor de automatizaciones en Docker: conecta formularios, correo, hojas de
cálculo, APIs de plataformas publicitarias y el vault, sin escribir código.

### Instalación (una sola vez)

**Paso 1 — Docker Engine dentro de Ubuntu.** No Docker Desktop: pesa menos, no
pide licencia comercial y no arranca con Windows.

```
curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER
```

**Paso 2 — cierra WSL y vuelve a abrir**, para que tome el grupo `docker`:

```
wsl --shutdown
```

**Paso 3 — genera la clave de cifrado.** n8n la usa para guardar las
credenciales de las cuentas que conectes. Si la pierdes, se pierden.

```
cd /mnt/c/Obsidian/dts-tools/n8n && echo "N8N_ENCRYPTION_KEY=$(openssl rand -hex 32)" > .env && chmod 600 .env
```

**Paso 4 — levanta el servicio:**

```
cd /mnt/c/Obsidian/dts-tools/n8n && docker compose up -d
```

Abre <http://localhost:5678> y crea tu cuenta de administrador.

### Operación

| Acción | Comando |
|---|---|
| Levantar | `docker compose up -d` |
| Apagar | `docker compose down` |
| Ver logs | `docker compose logs -f` |
| Actualizar | `docker compose pull && docker compose up -d` |
| Ver consumo | `docker stats n8n` |

**Apágalo cuando no lo uses.** WSL2 tiene 4 GB y n8n reserva hasta 1 GB.

### Decisiones tomadas en la configuración

- **Solo escucha en `127.0.0.1`.** No se expone a la red de la oficina ni a
  internet. Esta laptop no es un servidor: se suspende, cambia de red y tiene
  IP dinámica. Para acceso del equipo hace falta un mini-PC o un VPS.
- **El vault se monta solo-lectura** (`:ro`). Quita esa bandera solo cuando un
  flujo de verdad necesite escribir notas.
- **Purga de ejecuciones a 7 días**, y no guarda las exitosas. Sin esto el
  historial llena el disco.
- **La clave de cifrado vive en `.env`**, que está en `.gitignore`. Nunca en
  `docker-compose.yml`.

---

## 3. Entorno de desarrollo de skills

Node.js vía `nvm`, para construir y probar los skills propios de DTS.
Se instala en el home del usuario, sin `sudo` y sin tocar el sistema.

```
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
```

Cierra y reabre la terminal, luego:

```
nvm install --lts && node --version
```

---

## Notas

- El equipo anfitrión y la bitácora de cómo se montó WSL2 están documentados en
  el vault: `40-Proyectos/Servidor DTS — Fase 1 WSL2.md`.
- Nada de esto es infraestructura de producción. Es un entorno de desarrollo
  local en una laptop.
