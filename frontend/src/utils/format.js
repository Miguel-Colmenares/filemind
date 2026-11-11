export const fmtBytes = (n) => {
  if (n == null) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
};

export const fmtDate = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString('es-CO', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
};

export const fmtPct = (x, digits = 1) => (x == null ? '—' : `${(x * 100).toFixed(digits)} %`);
export const fmtNum = (x, digits = 3) => (x == null ? '—' : Number(x).toFixed(digits).replace('.', ','));

export const CATEGORY_LABEL = {
  Academico: 'Académico', Informes: 'Informes', Facturas: 'Facturas', Contratos: 'Contratos',
  Reuniones: 'Reuniones', Presentaciones: 'Presentaciones', Financiero: 'Financiero', Otros: 'Otros',
  // perfil jurídico
  Demandas: 'Demandas', Contestaciones: 'Contestaciones', Tutelas: 'Tutelas', Peticiones: 'Derechos de petición',
  Recursos: 'Recursos', Providencias: 'Sentencias y autos', Poderes: 'Poderes', Conciliaciones: 'Conciliaciones',
  Pruebas: 'Pruebas y anexos', Honorarios: 'Honorarios',
  // perfil constitucional (sentencias reales de la Corte Constitucional)
  Tutela: 'Tutela', Inconstitucionalidad: 'Demandas de inconstitucionalidad', Tratados: 'Tratados internacionales',
  DecretosLegislativos: 'Decretos legislativos', Objeciones: 'Objeciones a proyectos de ley',
};
export const catLabel = (c) => CATEGORY_LABEL[c] || c || '—';

// Color e ícono fijos por etiqueta: los mismos en chips, filtros, gráficas y carpetas
const CATEGORY_STYLE = {
  Tutela: ['#f97316', 'shield'], Tutelas: ['#f97316', 'shield'],
  Inconstitucionalidad: ['#8b5cf6', 'scale'], Tratados: ['#0ea5e9', 'globe'],
  DecretosLegislativos: ['#eab308', 'stamp'], Objeciones: ['#ec4899', 'ban'], Otros: ['#94a3b8', 'inbox'],
  Demandas: ['#ef4444', 'gavel'], Contestaciones: ['#14b8a6', 'mail'], Peticiones: ['#6366f1', 'mail'],
  Recursos: ['#f59e0b', 'arrowUp'], Providencias: ['#a855f7', 'gavel'], Poderes: ['#06b6d4', 'key'],
  Contratos: ['#10b981', 'edit'], Conciliaciones: ['#84cc16', 'users'], Pruebas: ['#64748b', 'search'],
  Honorarios: ['#d97706', 'money'], Academico: ['#22c55e', 'book'], Informes: ['#3b82f6', 'chart'],
  Facturas: ['#d97706', 'money'], Reuniones: ['#0891b2', 'users'], Presentaciones: ['#db2777', 'chart'],
  Financiero: ['#16a34a', 'money'],
};
const FALLBACK = ['#f97316', '#0ea5e9', '#8b5cf6', '#10b981', '#ec4899', '#eab308'];
export const catStyle = (c) => {
  if (CATEGORY_STYLE[c]) return { color: CATEGORY_STYLE[c][0], icon: CATEGORY_STYLE[c][1] };
  const h = [...(c || '')].reduce((a, ch) => a + ch.charCodeAt(0), 0);
  return { color: FALLBACK[h % FALLBACK.length], icon: 'tag' };
};
export const catColor = (c) => catStyle(c).color;

export const STATUS_LABEL = { clasificado: 'Clasificado', cuarentena: 'En cuarentena', duplicado: 'Duplicado', eliminado: 'Eliminado' };

export const EVENT_LABEL = {
  archivo_detectado: 'Archivo detectado', hash_calculado: 'Huella SHA-256 calculada',
  fase1_estatico: 'Fase 1 · Análisis estático', fase2_heuristico: 'Fase 2 · Análisis heurístico',
  controles_seguridad: 'Controles de ciberseguridad',
  fase3_sandbox: 'Fase 3 · Entorno aislado', fase4_puntaje: 'Fase 4 · Puntaje de riesgo',
  cuarentena: 'Enviado a cuarentena', clasificado: 'Clasificado', protocolo_completo: 'Protocolo completo',
  duplicado: 'Duplicado detectado', correccion_usuario: 'Corrección del usuario',
  liberado_de_cuarentena: 'Liberado de cuarentena', eliminado_de_cuarentena: 'Eliminado de cuarentena',
  acceso_denegado_cuarentena: 'Acceso denegado (cuarentena)', ignorado_grupo_no_monitoreado: 'Ignorado: grupo no monitoreado',
  grupos_configurados: 'Grupos configurados', servicio_iniciado: 'Servicio iniciado', servicio_detenido: 'Servicio detenido',
  modelo_reentrenado: 'Modelo reentrenado', conector_carpeta_iniciado: 'Conector de carpeta iniciado',
  exportacion_solicitada: 'Exportación de chat solicitada', exportacion_iniciada: 'Exportación iniciada',
  exportacion_terminado: 'Exportación terminada', exportacion_cancelado: 'Exportación cancelada',
  exportacion_error: 'Exportación con error', exportacion_guardada: 'Archivos seguros guardados en carpeta',
  exportacion_descargada: 'Exportación descargada en ZIP',
  guardado_en_carpeta_bufete: 'Guardado en la carpeta del bufete', error_carpeta_bufete: 'No se pudo guardar en la carpeta del bufete',
  carpeta_bufete_configurada: 'Carpeta del bufete configurada', carpeta_bufete_pendientes_guardados: 'Archivos pendientes guardados en la carpeta',
  whatsapp_desvinculado: 'WhatsApp desvinculado',
};
export const eventLabel = (e) => EVENT_LABEL[e] || e;
