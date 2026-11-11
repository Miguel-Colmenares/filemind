# Desplegar FileMind en un servidor

Guía para poner FileMind en un VPS (o cualquier máquina Linux con Docker) y usarlo desde el
navegador con HTTPS. Para correrlo en un PC sin Docker, mira el [README](README.md).

## Qué se despliega

| Servicio | Qué hace | Imagen |
|---|---|---|
| `filemind` | API FastAPI que también sirve la interfaz web (React compilada) | `Dockerfile` en la raíz |
| `whatsapp` | Puente con WhatsApp Web (whatsapp-web.js + Chromium) que envía los adjuntos a la API | `whatsapp-gateway/Dockerfile` |

La API escucha solo en `127.0.0.1:8000` del servidor. El acceso desde internet entra por un proxy
con HTTPS (Caddy o Nginx, más abajo).

## Requisitos

- Linux con Docker Engine 24+ y el plugin `docker compose` (v2.24 o más reciente).
- 2 GB de RAM como mínimo (Chromium del puente usa unos 500 MB) y 5 GB de disco.
- Un dominio apuntando a la IP del servidor si quieres HTTPS (recomendado).

## 1. Preparar y arrancar

```bash
git clone <url-del-repositorio> filemind && cd filemind
cp .env.example .env          # revisa y descomenta lo que necesites
mkdir -p bufete               # carpeta donde se guardan los archivos por etiqueta
docker compose up -d --build
docker compose ps             # «filemind» debe quedar healthy
```

La primera compilación tarda unos minutos porque instala scikit-learn, compila la interfaz y
descarga Chromium. Los modelos de IA ya entrenados vienen en `backend/data/modelos/`, así que no
hace falta entrenar nada.

Comprobación rápida en el servidor:

```bash
curl http://127.0.0.1:8000/health      # {"ok":true,...}
```

## 2. Primer administrador

Abre la página: la primera vez aparece **Crear administrador**. Esa cuenta puede crear las demás
desde **Usuarios**. Por terminal también se puede crear o restablecer una cuenta:

```bash
docker compose exec filemind python -m filemind usuario admin "Nombre Apellido" --rol admin
```

## 3. Vincular WhatsApp

1. Entra como administrador a **Chats de WhatsApp**.
2. En unos segundos aparece un **código QR**. En el celular del número que se va a usar abre
   WhatsApp → Dispositivos vinculados → Vincular un dispositivo y escanéalo.
3. Marca los chats cuyos archivos se van a analizar y pulsa **Guardar**.

La sesión queda en el volumen `whatsapp-sesion`. **Ese volumen debe persistir**: si se borra
(`docker compose down -v` o `docker volume rm`), hay que escanear el QR de nuevo. Reiniciar o
recompilar los contenedores no la borra. Para usar otro número: botón «Desvincular y usar otro
número» en la misma página.

Si el puente no conecta, mira su registro:

```bash
docker compose logs -f whatsapp
```

> El botón «Encender WhatsApp» de la interfaz es para la instalación en un PC. En Docker el puente
> es su propio servicio y se reinicia solo (`restart: unless-stopped`).

## 4. HTTPS detrás de un proxy

La API confía en las cabeceras `X-Forwarded-*` del proxy (`FORWARDED_ALLOW_IPS`), así la cookie
de sesión sale con el atributo `Secure` cuando se entra por HTTPS.

**Opción A, Caddy (certificado automático de Let's Encrypt).** Instala Caddy en el servidor y usa
este `/etc/caddy/Caddyfile`:

```
filemind.tudominio.com {
    encode gzip
    reverse_proxy 127.0.0.1:8000
    request_body {
        max_size 25MB
    }
}
```

```bash
sudo systemctl reload caddy
```

**Opción B, Nginx + Certbot.**

```nginx
server {
    server_name filemind.tudominio.com;
    client_max_body_size 25M;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 180s;
    }
    listen 80;
}
```

```bash
sudo certbot --nginx -d filemind.tudominio.com
```

Abre solo los puertos 80 y 443 en el cortafuegos. El 8000 no debe quedar expuesto.

## 5. Datos, copias de seguridad y actualizaciones

Todo lo que importa vive fuera de las imágenes:

| Dónde | Qué guarda |
|---|---|
| `backend/data/` | base SQLite (usuarios, archivos, auditoría), biblioteca, cuarentena cifrada, modelos y el token del puente (`api_token.txt`) |
| `bufete/` | copia de cada archivo seguro en la subcarpeta de su etiqueta (en Configuración se escoge `/bufete`) |
| volumen `whatsapp-sesion` | sesión vinculada de WhatsApp |
| volumen `whatsapp-pendientes` | archivos que esperan a que la API vuelva |

Copia de seguridad básica:

```bash
docker compose stop
tar czf filemind-respaldo-$(date +%F).tgz backend/data bufete
docker compose start
```

Actualizar a una versión nueva:

```bash
git pull
docker compose up -d --build
```

## 6. Seguridad del análisis aislado (Fase 3)

Con `FILEMIND_SANDBOX_BACKEND=docker` (lo que trae `docker-compose.yml`), cada archivo se ejecuta
en un contenedor desechable sin red, de solo lectura y sin privilegios. Para lanzar esos
contenedores, el servicio `filemind` monta el socket de Docker (`/var/run/docker.sock`), y **eso le
da control total de Docker en el servidor**. Úsalo solo en un servidor dedicado a FileMind.

Si el servidor es compartido o no quieres exponer el socket:

1. En `.env` pon `FILEMIND_SANDBOX_BACKEND=subprocess`.
2. En `docker-compose.yml` borra las líneas del socket y de `/tmp` del servicio `filemind`.

Con `subprocess` la Fase 3 corre en un proceso con límites de tiempo y memoria dentro del mismo
contenedor. Aísla menos que un contenedor desechable, pero las fases 1, 2 y 4 y la cuarentena
funcionan igual. Dentro de un contenedor, el modo `namespace` (unshare) suele no estar disponible
porque Docker no da esos privilegios.

## 7. Variables de entorno

Todas están explicadas en [`.env.example`](.env.example). Las más usadas:

| Variable | Para qué |
|---|---|
| `FILEMIND_PERFIL` | categorías del clasificador (`constitucional`, `juridico` o `general`) |
| `FILEMIND_SANDBOX_BACKEND` | `docker` o `subprocess` (sección 6) |
| `FILEMIND_VIRUSTOTAL_API_KEY`, `FILEMIND_MALWAREBAZAAR_API_KEY` | consultas opcionales a bases de malware |
| `FILEMIND_SESSION_HOURS` | duración de la sesión web |
| `NOTIFY_TO` | número que recibe las alertas por WhatsApp (`57XXXXXXXXXX@c.us`) |

Nunca subas el archivo `.env` al repositorio: ya está en `.gitignore`.

## Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| «Puente apagado» en Chats | `docker compose logs whatsapp`. Si dice que no encuentra el token, la API aún no arranca, espera a que `filemind` quede healthy |
| El QR no aparece | Chromium sin memoria: revisa `shm_size: 512m` y que el servidor tenga RAM libre |
| La sesión se cierra cada vez | El volumen `whatsapp-sesion` no persiste o se borró con `down -v` |
| No se puede iniciar sesión por HTTPS | El proxy no envía `X-Forwarded-Proto` o falta `FORWARDED_ALLOW_IPS` |
| Error 413 al subir archivos | Sube el límite del proxy (`client_max_body_size` o `max_size`) |
