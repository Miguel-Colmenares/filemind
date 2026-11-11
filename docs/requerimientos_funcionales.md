# Requerimientos funcionales de FileMind

RF1 a RF8 cubren la recepción, el protocolo de seguridad y la cuarentena. RF9 a RF12 describen la exportación de un chat de WhatsApp, la cola de revisión, la entrega organizada de los archivos seguros y el uso como aplicación de escritorio. RF13 exige mostrar qué encontró cada control de seguridad.

## Recepción de archivos

**RF1. Análisis automático solo de los chats escogidos.** El sistema debe analizar de forma automática únicamente los archivos que lleguen a los grupos o chats de WhatsApp que el usuario marque en la página Chats de WhatsApp. Los adjuntos de los demás chats no se descargan ni se guardan, y cada caso ignorado queda registrado en la auditoría.

**RF2. Detección oportuna de adjuntos.** El sistema debe detectar cada archivo nuevo de un chat monitoreado en un tiempo máximo de 10 segundos contados desde la hora del mensaje.

## Protocolo de seguridad

**RF3. Huella digital previa.** El sistema debe calcular la huella SHA-256 de cada archivo antes de cualquier otro procesamiento y usarla para detectar duplicados y dejar evidencia.

**RF4. Verificación del tipo real.** El sistema debe comparar la extensión declarada con el tipo real del archivo según su firma de bytes y detectar la doble extensión, los caracteres de texto invertido, los accesos directos y programas disfrazados y los archivos políglotas (por ejemplo, una imagen que además contiene un comprimido).

**RF5. Consulta de firmas de malware.** El sistema debe consultar la huella en un repositorio de firmas conocidas, local o externo, y registrar la consulta y su respuesta. La consulta local debe aceptar huellas SHA-256, SHA-1 y MD5, cargar listas adicionales (por ejemplo, exportaciones gratuitas de MalwareBazaar) y revisar también las huellas de lo que el archivo trae adentro.

**RF6. Detección de patrones de phishing y ransomware.** El sistema debe buscar en el contenido enlaces engañosos, lenguaje de urgencia o robo de credenciales, macros, código activo en PDF y otros indicadores de riesgo. Como mínimo debe analizar macros VBA y Excel 4.0 y objetos OLE incrustados; JavaScript, acciones automáticas y archivos incrustados en PDF; comprimidos anidados, con contraseña o bombas de descompresión; reglas YARA; entropía; enlaces ocultos; formularios HTML de credenciales, y peticiones de claves acompañadas de enlaces. Todos estos controles deben ejecutarse en el equipo, sin depender de servicios externos de pago.

**RF7. Puntaje de riesgo reproducible.** El sistema debe asignar a cada archivo un puntaje de 0 a 100 que combine reglas explicables y un modelo de inteligencia artificial, de modo que el mismo archivo obtenga siempre el mismo puntaje.

**RF8. Cuarentena y aviso.** Todo archivo con puntaje mayor que 70 debe guardarse cifrado en cuarentena, sin posibilidad de abrirlo ni descargarlo directamente, y el usuario debe recibir un aviso en lenguaje claro. Solo una liberación explícita, con motivo registrado, puede sacarlo de allí.

**RF13. Detalle de cada control.** Para cada archivo analizado, el sistema debe mostrar en la interfaz el resultado de cada control de seguridad (sin hallazgos, para revisar, con riesgo o no aplica), un resumen en lenguaje claro, el detalle de lo que encontró y los puntos de riesgo que aportó. Esto aplica también a los archivos que llegan por la exportación de un chat.

## Exportación y organización

**RF9. Exportación de todos los archivos de un chat.** Al escoger un grupo o chat en la página Chats de WhatsApp, el sistema debe mostrar el botón Exportar archivos. Al pulsarlo, todos los archivos del historial de ese chat deben entrar a una cola visible en forma de lista, aunque el chat no tenga activado el análisis automático.

**RF10. Revisión secuencial de la cola.** Cada archivo de la cola debe pasar, uno tras otro, por la huella, las cuatro fases del protocolo de seguridad y la clasificación temática. La lista debe mostrar en todo momento el estado de cada archivo (en cola, descargando, analizando, seguro, en cuarentena o no disponible), su categoría y su puntaje, y el usuario debe poder cancelar la exportación.

**RF11. Entrega organizada de los archivos seguros.** Al terminar la cola, el sistema debe permitir descargar los archivos seguros uno por uno o en un solo paquete comprimido. Además, el usuario debe poder escoger una carpeta de su equipo, y FileMind debe guardar allí los archivos seguros organizados en una subcarpeta por categoría (Tutela, Demandas de inconstitucionalidad, Tratados internacionales, Decretos legislativos y Objeciones a proyectos de ley). Los archivos con puntaje mayor que 70 deben permanecer en cuarentena y nunca copiarse a la carpeta destino.

**RF12. Aplicación de escritorio.** El sistema debe poder abrirse como una aplicación de escritorio en una ventana propia que inicie por sí misma el servidor de análisis y el puente de WhatsApp, sin que el usuario tenga que abrir terminales. La versión web debe seguir disponible con las mismas funciones.

## Retroalimentación

Los requerimientos de clasificación y retroalimentación del documento de inteligencia artificial siguen vigentes. El usuario puede corregir la categoría de un archivo, la corrección mueve el archivo a la carpeta correcta y queda guardada para reentrenar el modelo.
