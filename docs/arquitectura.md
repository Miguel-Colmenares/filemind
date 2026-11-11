# Arquitectura de FileMind

## Vista general

```mermaid
flowchart LR
    subgraph Usuario
      WA[WhatsApp<br/>grupos de la obra]
      NAV[Navegador]
    end
    subgraph "whatsapp-gateway (Node.js)"
      GW[index.js<br/>whatsapp-web.js]
    end
    subgraph "frontend (React + Vite)"
      UI[Interfaz web<br/>10 pantallas]
    end
    subgraph "backend (Python + FastAPI)"
      API[api/<br/>routers REST]
      SVC[services/<br/>analysis_service]
      SEC[security/<br/>fases 1-4]
      AI[ai/<br/>clasificador temático]
      INF[infrastructure/<br/>auditoría · almacenamiento · avisos]
      SBX[sandbox/worker.py<br/>proceso aislado]
    end
    WA -- adjunto de grupo monitoreado --> GW
    GW -- POST /api/ingest --> API
    GW -- GET /api/notificaciones --> API
    GW -- alerta en lenguaje claro --> WA
    NAV --> UI -- fetch /api/... --> API
    API --> SVC
    SVC --> SEC --> SBX
    SVC --> AI
    SVC --> INF
```

La interfaz compilada (`frontend/dist`) la sirve la misma API, así que en
producción basta un proceso de Python más el puente de WhatsApp.

## Capas del backend

Las dependencias van en una sola dirección: de arriba hacia abajo.

```mermaid
flowchart TB
    api["api/ · presentación<br/>app.py · deps.py · schemas.py · routes/*"]
    services["services/ · casos de uso<br/>analysis_service.FileMind"]
    security["security/ · protocolo<br/>static · signatures · heuristic · controls · sandbox · risk"]
    ai["ai/ · inteligencia artificial<br/>classifier · dataset · evaluation"]
    infra["infrastructure/ · adaptadores<br/>repository · storage · extract · notify · uptime · folder_connector"]
    domain["domain/ · modelo del dominio<br/>categorías · FileStatus · RiskLevel · umbral 70"]
    api --> services
    services --> security & ai & infra
    security --> domain
    ai --> domain
    infra --> domain
```

| Capa | Responsabilidad | No debe |
|---|---|---|
| `domain` | Conceptos del negocio: 8 categorías, estados del archivo, niveles de riesgo, umbral de cuarentena | Importar nada del resto del sistema |
| `security` | Las 4 fases del protocolo; cada fase es una función pura que recibe bytes y devuelve hallazgos | Escribir en disco o en la base de datos |
| `ai` | Entrenar, evaluar y usar el clasificador temático | Conocer HTTP ni WhatsApp |
| `infrastructure` | Todo lo que toca el mundo exterior: SQLite, archivos, cifrado, webhooks, carpetas | Tomar decisiones de riesgo |
| `services` | Orquestar el flujo completo y garantizar el orden (SHA-256 primero, RF3) | Contener reglas de detección |
| `api` | Validar entradas (Pydantic), autorización por token y respuestas HTTP | Contener lógica de negocio |

## Flujo de un archivo

```mermaid
sequenceDiagram
    participant G as Puente WhatsApp
    participant A as API
    participant S as analysis_service
    participant P as security (fases)
    participant X as sandbox (sin red)
    participant M as ai (clasificador)
    participant R as repository / storage
    G->>A: POST /api/ingest (archivo, grupo, hora del mensaje)
    A->>A: ¿grupo monitoreado? (RF1)
    A->>S: submit()
    S->>R: evento archivo_detectado
    S->>S: SHA-256 (RF3) · ¿duplicado?
    S->>P: Fase 1 estático (RF4, RF5)
    S->>P: Fase 2 heurístico (RF6)
    S->>P: 10 controles de ciberseguridad (RF4-RF6, RF13)
    S->>X: Fase 3 aislado (RNF5)
    S->>P: Fase 4 puntaje = máx(reglas, IA) (RF7)
    alt puntaje > 70
        S->>R: cuarentena cifrada + aviso (RF8, RNF7)
    else puntaje ≤ 70
        S->>M: clasificar tema
        S->>R: guardar en biblioteca/<Categoría>
    end
    S->>R: evento protocolo_completo (RNF8)
    A-->>G: resumen + aviso
```

## API REST

| Método | Ruta | Uso |
|---|---|---|
| GET | `/health` | Estado del servicio (RNF2) |
| GET | `/api/disponibilidad` | Disponibilidad del mes |
| GET | `/api/estadisticas` | Conteos por estado y categoría, tiempos |
| GET | `/api/categorias` · `/api/configuracion` | Catálogo y parámetros activos |
| GET · PUT | `/api/grupos` | Grupos monitoreados (RF1) |
| POST | `/api/ingest` | Recibir un archivo (RF2) |
| GET | `/api/archivos` · `/api/archivos/{sha}` | Listado con filtros y detalle con eventos |
| GET | `/api/archivos/{sha}/descargar` | Descarga; 403 si está en cuarentena (RF8) |
| POST | `/api/archivos/{sha}/categoria` | Corrección del usuario (retroalimentación) |
| POST · DELETE | `/api/cuarentena/{sha}/liberar` · `/api/cuarentena/{sha}` | Liberar con motivo y confirmación, o eliminar |
| GET · POST | `/api/modelos` · `/api/reentrenar` | Métricas y reentrenamiento |
| GET | `/api/eventos` · `/api/auditoria/retencion` | Auditoría (RNF8) |
| GET | `/api/notificaciones` | Avisos pendientes para el puente (RNF7) |

La documentación interactiva está en http://127.0.0.1:8000/docs y hay ejemplos
listos en [`api.http`](api.http).

## Interfaz web

`frontend/src/` separa `api/` (cliente HTTP único), `hooks/` (`useApi` con
refresco periódico), `components/` (piezas reutilizables: tarjetas, medidor de
riesgo, cajón de detalle, modales) y `pages/` (una por pantalla). El tema
claro/oscuro se define con variables CSS en `styles/app.css`.
