# Monitoreo en GitHub Actions

Saca el monitoreo de la laptop. A partir de aquí corre en los servidores de
GitHub cada 5 minutos, esté tu equipo encendido o no.

## Por qué el repositorio va a ser público

GitHub Actions es gratis e ilimitado en repositorios públicos. En privados da
2,000 minutos al mes, que a este ritmo alcanzan para correr apenas cada media
hora.

Para que sea seguro publicarlo:

- **Las credenciales nunca están en el código.** Viven en *Secrets* de GitHub,
  cifradas, y no aparecen ni en los logs.
- **El historial no lleva IPs.** El monitor las omite por defecto; hay que
  pedirlas explícitamente con `DTS_HISTORIAL_COMPLETO=1`. El historial que ya
  se había acumulado se limpió con `sanitizar.py`.
- **`estado.json` no se versiona.** Ese sí lleva IPs, y se queda local.
- Los dominios de `sitios.json` son públicos de todas formas: cualquiera puede
  escribirlos en un navegador.

Si prefieres el repositorio privado, cambia el cron a `*/30 * * * *` y cabe en
la cuota gratuita.

---

## Puesta en marcha

### 1. Crear el repositorio

En <https://github.com/new>:

- Nombre: `dts-tools`
- Visibilidad: **Public**
- **No** marques nada de "Initialize with README" — el repo local ya tiene
  historia y chocaría.

### 2. Subir el código

Desde PowerShell:

```
git -C "C:\Obsidian\dts-tools" remote add origin https://github.com/TU-USUARIO/dts-tools.git
```

```
git -C "C:\Obsidian\dts-tools" push -u origin master
```

### 3. Cargar las credenciales

En `https://github.com/TU-USUARIO/dts-tools/settings/secrets/actions`,
botón **New repository secret**, dos veces:

| Nombre | Valor |
|---|---|
| `WP_USER` | tu usuario de WordPress |
| `WP_APP_PASSWORD` | el Application Password de digitalts.com.mx |

El Application Password se genera en
<https://digitalts.com.mx/wp-admin/profile.php> → *Application Passwords* →
nombre `DTS Monitor` → **Add New**. Se muestra una sola vez.

### 4. Encender

En la pestaña **Actions** del repositorio, workflow *Monitor GICSA*,
botón **Run workflow**. La primera corrida confirma que los secrets funcionan.

De ahí en adelante corre solo cada 5 minutos.

---

## Cómo queda repartido el trabajo

| | Laptop | GitHub Actions |
|---|---|---|
| Frecuencia | cada minuto | cada 5 minutos |
| Bitácora en Obsidian | ✅ | ❌ no hay vault |
| Dashboard interno `localhost:8099` | ✅ | ❌ |
| Publica en digitalts.com.mx | ✅ | ✅ |
| Depende de que la laptop esté encendida | ✅ | ❌ |

Los dos pueden convivir: la laptop da el detalle fino y la bitácora en el
vault mientras trabajas; GitHub Actions garantiza que el sitio público siga
actualizándose de noche, en fin de semana y en vacaciones.

Si prefieres que solo corra en GitHub, quita la tarea de Windows:

```
schtasks /delete /tn "DTS Monitor GICSA" /f
```

---

## Lo que GitHub Actions no puede hacer

- **Menos de 5 minutos.** Es el mínimo de la plataforma.
- **Puntualidad exacta.** Bajo carga, GitHub retrasa los cron unos minutos.
  Para disponibilidad no importa; para alertas al segundo, sí.
- **n8n y el dashboard interno.** Necesitan un servidor encendido. Se quedan
  en la laptop hasta que haya VPS.
- **Ver sitios de red interna.** Solo alcanza lo que es público en internet.

---

## Variables de entorno

| Variable | Para qué |
|---|---|
| `DTS_VAULT` | Ruta del vault. Si no existe, se omite la bitácora sin error |
| `DTS_HISTORIAL_COMPLETO` | `1` para guardar IPs en el historial. Apagado por defecto |
| `WP_USER` / `WP_APP_PASSWORD` | Credenciales de publicación |
