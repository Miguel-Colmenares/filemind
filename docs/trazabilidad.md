# Matriz de trazabilidad de requisitos

Los requisitos están en [`requerimientos_funcionales.md`](requerimientos_funcionales.md). Todas las
pruebas están en `backend/tests/` y se ejecutan con `python -m pytest` desde `backend/`.

## Requisitos funcionales

| ID | Requisito | Implementación | Verificación (criterio del documento) | Resultado |
|---|---|---|---|---|
| RF1 | Monitorear solo los grupos configurados | `services.analysis_service.FileMind.is_monitored`, tabla `groups`, filtro en `whatsapp-gateway/index.js` (no descarga) | `test_rf1_solo_grupos_configurados`: archivos de otros grupos no se procesan ni guardan; queda el evento `ignorado_grupo_no_monitoreado`. Conexión activa en log del puente (`[conexión] activa`) y evento `servicio_iniciado` | ✅ |
| RF2 | Detectar adjuntos en ≤ 10 s | Evento `message` del puente → `/api/ingest` con `message_ts`; conector por carpeta | `test_rf2_latencia_registrada` + `backend/scripts/pruebas_rendimiento.py` (10 archivos de 0,01 a 10 MB) | prom. 2,4 s, máx. 3,6 s ✅ |
| RF3 | SHA-256 antes de todo | `security.static.sha256_bytes`, primer paso de `analysis_service.process` | `test_rf3_sha256_antes_de_procesar`: igual a `sha256sum` y el evento `hash_calculado` precede a la Fase 1 | ✅ |
| RF4 | Extensión vs. magic number | `security.static.detect_type` (incluye inspección interna ZIP/OOXML para distinguir docx/docm/xlsx/pptx; LNK, ISO, CAB, audio y video), `analyze_name` (doble extensión, RTLO); control `tipo_real` de `security/controls.py` (políglotas) | `test_rf4_extensiones_falsificadas`: 12 archivos con extensión falsificada; `test_rf4_doble_extension_y_rtlo`; `test_controles_detectan_tecnicas_nuevas[poliglota_jpg_zip, lnk_disfrazado]` | 12/12 ✅ |
| RF5 | Consultar hash en repositorio de firmas | `security.signatures.SignatureRepository` (local + caché + MalwareBazaar + VirusTotal; listas en `data/firmas/` con SHA-256, SHA-1 o MD5); control `hashes` (también huellas internas); `scripts/actualizar_firmas.py` | `test_rf5_firma_conocida` (archivo EICAR); `test_controles_firmas_md5_y_listas`; `test_controles_detectan_tecnicas_nuevas[zip_eicar]`; la consulta queda en `fase1_estatico.signature_query` y en `controles_seguridad` | ✅ |
| RF6 | Patrones de phishing y ransomware | `security/heuristic.py` (URLs, lenguaje, macros VBA con oletools, PDF, OOXML, PowerShell, ofuscación) + `security/controls.py` (macros y OLE con oletools, PDF con PyMuPDF, comprimidos, YARA con `security/reglas/*.yar`, entropía, URL ocultas, HTML, ingeniería social) + `backend/sandbox/worker.py` (contenido oculto al desempaquetar) | `test_rf6_patrones`, `test_rf6_legitimo_sin_hallazgos`, `test_controles_detectan_tecnicas_nuevas` (15 técnicas), `test_controles_sin_falsos_positivos` (7 casos legítimos difíciles); dataset de 700 archivos + 89 de técnicas nuevas; `scripts/evaluar_controles.py` → `reportes/controles_metricas.json` | ✅ FN 57 % → 0 % en técnicas nuevas, 0 % FP |
| RF7 | Puntaje 0-100 reproducible | `security.risk.rule_score` (pesos documentados) + `RiskModel` | `test_rf7_puntaje_0_100_reproducible`; criterios en `docs/protocolo_riesgo.md` | ✅ |
| RF8 | Cuarentena > 70, sin apertura directa, notificar | `infrastructure.storage.quarantine_file` (cifrado Fernet, 0400, sin extensión original), API devuelve 403, liberación con confirmación y motivo | `test_rf8_cuarentena_cifrada_y_acceso_restringido`, `test_rf8_api_bloquea_descarga_y_exige_confirmacion` | ✅ |
| RF9 | Exportar todos los archivos de un chat escogido | Botón «Exportar archivos» en `frontend/src/pages/Groups.jsx`; `services.export_service.ExportManager`; el puente toma el trabajo de `/api/exportaciones/pendiente` y lee el historial (`whatsapp-gateway/index.js`, `mediaOfChat`) | `test_rf9_rf10_rf11_exportar_chat_en_cola_y_guardar_por_categoria`: un chat no monitoreado se exporta completo y queda el evento `exportacion_solicitada` | ✅ |
| RF10 | Revisar la cola archivo por archivo, a la vista | El puente sube un archivo y espera su resultado antes del siguiente; `ExportManager.analyze` aplica el protocolo completo con `FileMind.process(explicit=True)`; `components/ExportQueue.jsx` muestra el estado de cada uno | Misma prueba: los archivos en cola bajan de uno en uno y los estados finales son seguro, seguro, cuarentena | ✅ |
| RF11 | Entregar los seguros ordenados por categoría | `ExportManager.save_to` copia a la carpeta escogida con una subcarpeta por categoría; `ExportManager.zip_bytes` arma el ZIP; selector nativo de carpeta (pywebview o tkinter) | Misma prueba: `Contratos/contrato.docx` existe en el destino y en el ZIP, el `.pdf.exe` no se copia, evento `exportacion_guardada` | ✅ |
| RF12 | Usarse como aplicación de escritorio | `filemind/desktop.py` (pywebview + Edge WebView2) arranca la API y el puente si no estaban corriendo; `FileMind.bat` | Arranque manual de la ventana; la versión web sigue en `http://127.0.0.1:8000` | ✅ |
| RF14 | Importación incremental: al volver a exportar un chat solo se descargan los archivos nuevos | Tabla `imported` (chat, id del mensaje, huella); `ExportManager._skip_known` marca «ya importado» y «misma huella» antes de descargar; el puente envía la huella SHA-256 de WhatsApp (`lib.hashHex`) y solo baja lo que quedó en cola; opción «Todo de nuevo» (`completo=true`) | `test_entrega3.py::test_importacion_incremental_solo_trae_lo_nuevo` (2.ª exportación sube 1 de 4; otro chat con el mismo archivo no descarga nada), `test_huella_invalida_no_omite` | ✅ |
| RF15 | Explicar cada clasificación | `TopicClassifier.explain`: aporte = TF-IDF × peso de la clase; se muestra en el detalle del archivo | `test_explicacion_de_la_clasificacion` | ✅ |
| RF16 | Vigilar la salud del modelo en uso | `ai/health.py` (confianza media y % a revisión frente a la prueba; recomienda reentrenar) en `/api/modelos` | `test_salud_del_modelo` | ✅ |
| RF13 | Mostrar qué encontró cada control | `report.controls` (estado, resumen, detalle, puntos), evento `controles_seguridad`; `frontend/src/components/SecurityControls.jsx` en el paso «Controles» de *Analizar archivo* y en el detalle de cada archivo (también los de una exportación) | `test_controles_en_reporte_y_auditoria`: 10 controles en el reporte y el evento entre la Fase 2 y la Fase 4 | ✅ |

## Requisitos no funcionales

| ID | Atributo | Implementación | Métrica | Resultado |
|---|---|---|---|---|
| RNF1 | Rendimiento ≤ 15 s / 20 MB | Fases acotadas (límites de lectura, sandbox con timeout de 8 s) | Promedio sobre 30 archivos (`pruebas_rendimiento.py`), `test_rnf1_tiempo_por_archivo_20mb` | prom. 0,35 s, máx. 2,7 s ✅ |
| RNF2 | Disponibilidad ≥ 98 % | `infrastructure.uptime.UptimeMonitor` (latido por minuto), `/health`, `/api/disponibilidad`, `restart: unless-stopped`, reconexión del puente con vigilante cada 60 s, reinicio por página muerta y espera exponencial 5 s → 5 min (`whatsapp-gateway/lib.js`), reintentos de descarga y cola en disco `.pendientes/` | % de minutos con latido en el mes; `npm test` en `whatsapp-gateway` (8 pruebas, incluye el escenario real de 29 errores «detached Frame») | Se mide en operación; peor caso de recuperación 66 s (antes 7,5 h sin reconexión) ✅ |
| RNF3 | Falsos negativos ≤ 5 % | Puntaje = máx(reglas, IA) + reglas de alta confianza | Matriz de confusión binaria (umbral 70) en prueba + validación cruzada 5 particiones | 0 % / 2,4 % ✅ |
| RNF4 | Falsos positivos ≤ 10 % | Casos difíciles legítimos en el dataset (macros de formato, PDF con OpenAction, avisos urgentes reales) | Ídem | 0 % / 0 % ✅ |
| RNF5 | Sandbox sin red y sin persistencia | Docker `--network none --read-only --tmpfs /tmp --cap-drop ALL`; alterno `unshare --net` + usuario `nobody` + `RLIMIT_FSIZE=0`; directorio temporal borrado | `test_rnf5_sandbox_aislado_y_efimero`: sondas de red y escritura desde dentro + verificación de que no quedó ningún archivo | ✅ |
| RNF6 | 10 grupos, degradación ≤ 20 % | Cola con `ThreadPoolExecutor` (hilos configurables) | Prueba de carga 1 vs 10 grupos (1 archivo cada ~3 s por grupo, 30 s) | −26 % (sin degradación) ✅ |
| RNF7 | Notificaciones claras | `infrastructure.notify.build_message`: motivo primero, acción concreta, sin siglas | `test_rnf7_notificacion_sin_jerga` y `test_controles_lenguaje_claro` (reglas YARA y controles) (lista de términos técnicos prohibidos). **Pendiente:** encuesta a 5 usuarios (plantilla en `docs/encuesta_rnf7.md`) | Automático ✅ / Encuesta: por aplicar |
| RNF8 | Trazabilidad ≥ 6 meses | `infrastructure.repository.AuditStore`: SQLite + `audit.jsonl` de solo anexado, marca UTC en ms, retención mínima forzada a 183 días | `test_rnf8_trazabilidad_y_retencion`; `/api/auditoria/retencion` | ✅ |

## Requisitos del documento de IA

| Objetivo | Implementación | Evidencia |
|---|---|---|
| Detectar y recibir archivos de grupos específicos | Puente WhatsApp + `/api/ingest` + exportación de un chat + conector carpeta | RF1/RF2/RF9 |
| Desarrollar y entrenar un modelo que determine la categoría | `ai/classifier.py`: TF-IDF (palabras + caracteres) y comparación NaiveBayes / Regresión logística / SVM lineal / Random Forest; división 70/20/10 | `backend/reportes/tema_*.png`, `tema_metricas.json` |
| Clasificar y organizar en carpetas | `infrastructure.storage.Storage.store` → `data/biblioteca/<Categoría>/` | `test_clasificacion_y_duplicados` |
| Retroalimentación del usuario (diagrama de la propuesta) | Corrección en la interfaz (detalle del archivo) → tabla `feedback` → `/api/reentrenar` | `test_retroalimentacion_mueve_y_registra` |
| Problema: duplicación de documentos | Detección por SHA-256 | `test_clasificacion_y_duplicados` |
