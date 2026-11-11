# Protocolo de puntaje de riesgo (RF7)

El puntaje se calcula en `backend/filemind/security/risk.py` y es **reproducible**: con el
mismo archivo y el mismo modelo guardado siempre da el mismo valor (lo verifica
`test_rf7_puntaje_0_100_reproducible`).

## 1. Puntaje por reglas

Suma de los pesos de los indicadores presentes, con tope por indicador y tope global de 100.

| Característica | Indicador | Peso | Tope |
|---|---|---|---|
| `known_malware` | Hash en repositorio de malware | 100 | 100 |
| `executable_content` | Contenido ejecutable (MZ/ELF/script) | 90 | 90 |
| `double_extension` | Doble extensión (factura.pdf.exe) | 60 | 60 |
| `bidi_override` | Carácter RTLO en el nombre | 50 | 50 |
| `dangerous_ext` | Extensión peligrosa (.exe, .js, .vbs…) | 40 | 40 |
| `extension_mismatch` | Extensión no coincide con firma real | 35 | 35 |
| `macro_autoexec` | Macro con autoejecución (AutoOpen…) | 35 | 35 |
| `has_macros` | Contiene macros | 15 | 15 |
| `macro_suspicious` | Llamada peligrosa en VBA (Shell, CreateObject…) c/u | 10 | 30 |
| `pdf_launch` | PDF con /Launch | 40 | 40 |
| `pdf_javascript` | PDF con JavaScript | 25 | 25 |
| `pdf_hex_obfuscation` | PDF con nombres ofuscados (#xx) | 25 | 25 |
| `pdf_openaction` | PDF con /OpenAction | 8 | 8 |
| `pdf_autoaction` | PDF con /AA | 8 | 8 |
| `pdf_embedded` | PDF con archivos incrustados | 15 | 15 |
| `remote_template` | Plantilla remota (OOXML) | 75 | 75 |
| `dde` | Campo DDE/DDEAUTO | 75 | 75 |
| `ole_objects` | Objeto OLE incrustado c/u | 10 | 20 |
| `powershell` | PowerShell codificado / descarga | 75 | 75 |
| `url_ip_host` | URL con IP c/u | 20 | 40 |
| `url_shortener` | URL acortada c/u | 10 | 20 |
| `url_punycode` | URL con punycode | 25 | 25 |
| `url_risky_tld` | URL con TLD de alto abuso c/u | 15 | 30 |
| `url_at_sign` | URL con '@' | 20 | 20 |
| `url_brand_impersonation` | URL que suplanta una marca | 35 | 35 |
| `url_recent_domain` | Dominio registrado hace < 30 días | 25 | 25 |
| `phish_phrases` | Frase de urgencia/credenciales c/u | 8 | 32 |
| `ransom_phrases` | Frase de nota de rescate c/u | 25 | 75 |
| `sbx_embedded_exe` | Sandbox: ejecutable escondido | 75 | 75 |
| `sbx_hidden_scripts` | Sandbox: script oculto en base64 | 75 | 75 |
| `sbx_ransom_markers` | Sandbox: marcador de ransomware c/u | 10 | 30 |
| `sbx_hidden_objstm` | Sandbox: JS/Launch en flujo comprimido | 75 | 75 |
| `sbx_expansion_limit` | Sandbox: bomba de descompresión | 30 | 30 |
| `js_obfuscation` | ≥ 2 patrones de JS ofuscado (eval, unescape, fromCharCode) | 15 | 15 |
| `long_base64` | ≥ 3 bloques base64 largos | 10 | 10 |
| `url_credential_path` | Ruta de login/verificación **y** otro indicador de URL | 10 | 10 |
| `sbx_failed` | El análisis aislado excedió el tiempo | 20 | 20 |

Los indicadores de **alta confianza** (DDE, plantilla remota, PowerShell codificado,
ejecutable o script escondido, JavaScript en flujos comprimidos, nota de rescate) pesan
75: por sí solos llevan a cuarentena aunque el modelo nunca haya visto ese ataque.

### 1.1 Indicadores de los controles de ciberseguridad

`backend/filemind/security/controls.py` agrega diez controles locales (sin servicios
externos) que se ejecutan después de la Fase 2. Cada uno deja en el reporte su estado
(`ok`, `aviso`, `alerta`, `no_aplica`), un resumen, el detalle de lo que encontró y los
puntos que aportó; la interfaz los muestra en el paso «Controles» de *Analizar archivo* y
en el detalle de cada archivo. Sus indicadores **solo suman al puntaje por reglas**: no
entran al modelo de IA, que se entrenó con las 47 características originales y no cambia.

| Control | Característica | Indicador | Peso | Tope |
|---|---|---|---|---|
| Tipo real | `polyglot` | Imagen o PDF con un ZIP pegado (políglota) | 40 | 40 |
| Hashes | `known_malware_hash` | MD5 o SHA-1 en una lista local (`data/firmas_malware.txt`, `data/firmas/*.txt\|csv`) | 100 | 100 |
| Hashes | `inner_known_malware` | Algo que trae adentro (entrada de ZIP, adjunto de PDF, paquete OLE) está en la lista | 100 | 100 |
| Macros y OLE | `vba_ioc` | Indicadores en el código VBA (URL, IP, ejecutables) según oletools, c/u | 10 | 20 |
| Macros y OLE | `vba_obfuscation` | Cadenas hex/base64/Dridex en el VBA según oletools, c/u | 10 | 20 |
| Macros y OLE | `vba_stomping` | Código compilado distinto del código fuente | 60 | 60 |
| Macros y OLE | `xlm_macros` | Hoja de macros Excel 4.0 | 40 | 40 |
| Macros y OLE | `ole_package_exe` | Objeto OLE «Package» con un programa o script | 75 | 75 |
| Macros y OLE | `ole_exploit_class` | Objeto OLE de clase usada en exploits (Equation.3, OLE2Link) | 75 | 75 |
| Macros y OLE | `office_encrypted` | Documento de Office con contraseña | 20 | 20 |
| PDF | `pdf_js_autorun` | JavaScript o /Launch que se ejecuta al abrir (/OpenAction, /AA o árbol /Names) | 50 | 50 |
| PDF | `pdf_js_suspicious_api` | Función peligrosa en el JavaScript (launchURL, exportDataObject, util.printf…) c/u | 20 | 40 |
| PDF | `pdf_embedded_exe` | Programa o script incrustado | 75 | 75 |
| PDF | `pdf_embedded_macro` | Documento con macros incrustado | 30 | 30 |
| PDF | `pdf_encrypted` | PDF con contraseña de apertura | 15 | 15 |
| PDF | `pdf_malformed` | PDF dañado que no se puede abrir | 20 | 20 |
| Comprimidos | `archive_executable` | Programa real (por bytes mágicos) dentro del comprimido | 75 | 75 |
| Comprimidos | `archive_dangerous_entry` | Entrada con nombre de programa o script (.exe, .js, .vbs, .lnk…) | 60 | 60 |
| Comprimidos | `archive_path_traversal` | Rutas con `..` o absolutas | 40 | 40 |
| Comprimidos | `archive_bomb` | Relación de compresión > 1000:1 (> 1500:1 en Office) o > 1 GB declarado | 75 | 75 |
| Comprimidos | `archive_ratio_high` | Relación de compresión > 100:1 | 40 | 40 |
| Comprimidos | `archive_encrypted` | Entradas protegidas con contraseña | 30 | 30 |
| Comprimidos | `archive_nested_deep` | Tres niveles de comprimidos anidados | 20 | 20 |
| Comprimidos | `archive_macro_doc` | Documento con macros dentro del comprimido | 25 | 25 |
| Comprimidos | `archive_uninspectable` | Formato que no se puede listar (RAR, 7z, CAB, ISO…) | 10 | 10 |
| YARA | `yara_alta` | Coincidencia con una regla de severidad alta (`security/reglas/*.yar`) | 75 | 75 |
| YARA | `yara_media` | Coincidencia con una regla de severidad media, c/u | 20 | 40 |
| Entropía | `entropy_anomaly` | Texto con entropía > 5,8, contenido desconocido > 7,5 o programa empaquetado > 7,2 | 15 | 15 |
| URL | `url_hidden_suspicious` | Enlace sospechoso que no aparece en el texto visible, c/u | 20 | 40 |
| HTML | `html_password_form` | Formulario con campo de contraseña | 35 | 35 |
| HTML | `html_form_external` | Formulario que envía a un sitio no oficial | 20 | 20 |
| HTML | `html_brand_title` | Título que imita una marca con formulario ajeno | 20 | 20 |
| HTML | `url_text_mismatch` | El texto del enlace muestra un dominio y lleva a otro | 30 | 30 |
| HTML | `html_meta_refresh` | Redirección automática a otro sitio | 15 | 15 |
| HTML | `html_hidden_iframe` | Iframe oculto | 30 | 30 |
| Ingeniería social | `cred_request_link` | Pide claves o datos bancarios **y** da un enlace sospechoso (o no oficial en un texto corto) | 30 | 30 |

Las reglas YARA (`backend/filemind/security/reglas/filemind.yar`) cubren: archivo EICAR,
ejecutable incrustado o en base64, PowerShell codificado o de descarga, macros con
autoejecución y comandos, macros que descargan y guardan, binarios de Windows abusados
(certutil, bitsadmin, mshta, regsvr32, rundll32), borrado de copias de seguridad, notas de
rescate, DDE, macros Excel 4.0 que ejecutan, PDF con /Launch, contrabando HTML, scripts
WSH, JavaScript ofuscado, formularios de credenciales, objetos RTF de exploits y accesos
directos LNK. Se aplican al archivo y a todo lo desempaquetado (entradas de ZIP y de
Office, flujos PDF descomprimidos, adjuntos y código VBA). Se pueden agregar reglas en
cualquier `.yar` de esa carpeta.

## 2. Probabilidad del modelo de IA

Un clasificador (se elige el mejor de Regresión logística, Árbol de decisión, Random
Forest y Gradient Boosting en validación) recibe las 47 características de las fases
1-3 y estima P(legítimo), P(phishing) y P(ransomware).
P(malicioso) = 1 − P(legítimo).

## 3. Puntaje final

```
puntaje = max(reglas, round(100 × P(malicioso)))
si hash conocido (SHA-256, MD5, SHA-1 o interno) → 100
si ejecutable, doble extensión o RTLO          → al menos 90
```

Se toma el máximo para priorizar no dejar pasar amenazas (RNF3): basta con que la
evidencia documentada **o** el modelo sean contundentes.

| Nivel | Rango | Acción |
|---|---|---|
| Bajo | 0 – 39 | Se clasifica y guarda. |
| Medio | 40 – 70 | Se clasifica y guarda con advertencia al usuario. |
| Alto | > 70 | **Cuarentena cifrada** y notificación (RF8). |

## 4. Ejemplo

`factura_pendiente.pdf.exe` (cabecera MZ): `executable_content` 90 + `double_extension` 60
+ `dangerous_ext` 40 + `extension_mismatch` 35 + `sbx_embedded_exe` 75 → reglas = 100 (tope).
P(malicioso) = 1,00 → **puntaje 100, cuarentena**.

## 5. Evaluación (umbral 70, conjunto de prueba no visto)

Ver `reportes/riesgo_metricas.json` y `reportes/riesgo_matriz_confusion_binaria.png`.
Incluye validación cruzada de 5 particiones y la prueba de **ataques no vistos**
(se excluye un tipo de ataque del entrenamiento y se mide si se detecta), que muestra
que la combinación reglas + IA generaliza mejor que la IA sola.

## 6. Qué cambió con los controles de ciberseguridad (7 de octubre de 2026)

Medido con `python scripts/evaluar_controles.py` (desde `backend/`), que pasa cada
muestra inerte por el protocolo completo y calcula el puntaje sin y con los controles.
Resultado completo en `backend/reportes/controles_metricas.json`. La columna «solo
reglas» es lo que se detecta aunque el modelo de IA nunca haya visto ese ataque.

**Dataset original (700 archivos: 360 legítimos, 340 maliciosos)**

| Tipo | Cuarentena final antes → después | Solo reglas antes → después |
|---|---|---|
| ransomware/pdf_js | 82 % → 100 % | 0 % → 100 % |
| ransomware/pdf_objstm (JS en flujos de objetos) | 73 % → 100 % | 73 % → 100 % |
| ransomware/pdf_hex (nombres ofuscados) | 100 % → 100 % | 33 % → 100 % |
| phishing/html_login | 100 % → 100 % | 0 % → 100 % |
| phishing/completo | 100 % → 100 % | 84 % → 100 % |
| phishing/suplantacion_marca | 100 % → 100 % | 77 % → 97 % |
| phishing/sutil | 100 % → 100 % (en entrenamiento) | 0 % → 0 % en cuarentena; 0 % → 92 % con aviso (nivel medio) |
| Global maliciosos (falsos negativos) | 1,8 % → 0 % | 30,3 % → 14,7 % |
| Global legítimos (falsos positivos) | 0 % → 0 % | 0 % → 0 % |

El phishing sutil (un solo enlace acortado y una frase) sigue sin ir a cuarentena por
reglas: ahora sube de 23 a 51 puntos en promedio y queda como **riesgo medio**, es decir,
se entrega con advertencia en vez de pasar como seguro. En la prueba de ataques no vistos
del modelo (`riesgo_metricas.json`) seguía en 0 % de cuarentena; ese límite se mantiene y
se documenta.

**Técnicas nuevas (89 archivos inertes de `data/dataset/seguridad_controles`)**

| Técnica | Cuarentena antes → después |
|---|---|
| ZIP con .js en tres niveles, con contraseña, con rutas `../`, bomba, con EICAR | 0 % → 100 % |
| ZIP con un .docm con macros | 50 % → 100 % |
| Imagen JPG con un ZIP pegado (políglota) | 0 % → 100 % |
| PDF con JavaScript en el árbol /Names | 100 % → 100 % (solo reglas 0 % → 100 %) |
| RTF con objeto Equation.3 o con paquete .exe | 0 % → 100 % |
| Hoja de cálculo con macros Excel 4.0 | 0 % → 100 % |
| HTML con enlace engañoso e iframe oculto | 100 % → 100 % (solo reglas 0 % → 100 %) |
| ZIP con .exe, PDF con .exe adjunto, contrabando HTML, acceso directo .lnk disfrazado | 100 % → 100 % |
| Legítimos difíciles (factura electrónica ZIP con PDF+XML, ZIP con contraseña de nómina, fotos, PDF con XML adjunto, Word con Excel incrustado, boletín HTML, RTF) | 0 % → 0 % falsos positivos |
| Global | falsos negativos 57,4 % → 0 %; falsos positivos 0 % → 0 % |

También se revisaron los 82 archivos reales de `data/biblioteca`: ninguno subió de
nivel por los controles. Para no marcar archivos normales se ajustaron dos cosas: las notas de voz y
videos (OGG, MP3, MP4, WebM…) ahora se reconocen por su firma de bytes, y confundir
dos formatos de imagen (un sticker `.webp` guardado como `.jpeg`) ya no cuenta como
extensión falsificada.
