"""Generador del dataset sintético de documentos (componente de IA).

El documento de IA propone construir un dataset de documentos organizados
manualmente por categoría. Como punto de partida reproducible, este módulo
genera documentos realistas en español (contexto: Constructora Vichada S.A.S.
y entorno académico) en los formatos del alcance: PDF, Word, Excel,
PowerPoint y texto. El equipo puede añadir documentos reales anonimizados en
``data/dataset_real/<Categoria>/`` y se mezclan automáticamente.

Las plantillas comparten vocabulario entre categorías a propósito (un informe
financiero se parece a un presupuesto; un acta menciona contratos) para que
la tarea no sea trivial y las métricas sean creíbles.
"""
from __future__ import annotations

import io
import random
from pathlib import Path

from ..domain.models import CATEGORIES, PROFILE
from .dataset_juridico import COMUNES_JURIDICO, FORMAT_BIAS_JURIDICO, TEMPLATES_JURIDICO, juridico_ctx

PROYECTOS = ["vía Puerto Gaitán - Puerto Carreño", "pavimentación Av. 40 Villavicencio",
             "puente sobre el río Guatiquía", "mejoramiento vía Cumaral - Restrepo",
             "rehabilitación corredor Granada - San José", "placa huella vereda La Cumbre",
             "doble calzada Villavicencio - Acacías", "drenajes vía Puerto López"]
PERSONAS = ["Ing. Laura Méndez", "Arq. Carlos Rincón", "Ing. Andrés Pardo", "Dra. Paola Suárez",
            "Ing. Nelson Quiroga", "Sr. Jorge Useche", "Ing. Juan Vargas", "Lic. Diana Moreno",
            "Ing. Miguel Colmenares", "Sra. Martha Gaitán"]
PROVEEDORES = ["Agregados del Llano S.A.S.", "Asfaltos Meta Ltda.", "Ferretería La 40",
               "Maquinaria Orinoquía S.A.S.", "Transportes Vichada", "Concretos Llaneros S.A."]
MATERIAS = ["Inteligencia Artificial", "Seguridad de la Información", "Bases de Datos",
            "Cálculo Diferencial", "Ingeniería de Software", "Estadística", "Redes de Computadores"]
ITEMS = ["concreto 3000 psi", "acero de refuerzo 1/2\"", "mezcla asfáltica MDC-19", "base granular",
         "subbase granular", "alquiler retroexcavadora", "tubería PVC 8\"", "geotextil NT 1600",
         "señalización vertical", "combustible ACPM", "cemento gris x 50 kg", "arena de río"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]

# Frases compartidas que añaden ruido realista entre categorías
COMUNES = [
    "Se adjunta el documento para su revisión.", "Cualquier inquietud quedo atento.",
    "Favor confirmar recibido por este medio.", "Documento generado para el proyecto {p}.",
    "Villavicencio, {d} de {m} de 2026.", "Cordial saludo.", "Constructora Vichada S.A.S.",
    "Se solicita revisar el valor total y el cronograma.", "Enviado desde el grupo de obra.",
    "Pendiente la firma del residente.", "Ver anexos en la carpeta compartida.",
]


def _r(rng, seq):
    return rng.choice(seq)


def _money(rng, lo=200_000, hi=450_000_000):
    return f"${rng.randint(lo, hi):,}".replace(",", ".")


def _ctx(rng):
    return {"p": _r(rng, PROYECTOS), "per": _r(rng, PERSONAS), "prov": _r(rng, PROVEEDORES),
            "mat": _r(rng, MATERIAS), "m": _r(rng, MESES), "d": rng.randint(1, 28),
            "n": rng.randint(1, 60), "v": _money(rng), "it": _r(rng, ITEMS),
            "it2": _r(rng, ITEMS), "pct": rng.randint(5, 98)}


TEMPLATES: dict[str, list[list[str]]] = {
    "Academico": [
        ["Universidad Cooperativa de Colombia", "Taller {n} de {mat}", "Estudiante: {per}",
         "Resuelva los siguientes ejercicios y entregue antes del {d} de {m}.",
         "1. Explique el concepto visto en clase.", "2. Desarrolle el ejercicio propuesto en el laboratorio.",
         "Criterios de evaluación: rúbrica del docente, nota sobre 5.0."],
        ["Trabajo final de {mat}", "Integrantes: {per} y compañeros", "Introducción", "Marco teórico",
         "Metodología", "Conclusiones", "Referencias bibliográficas en formato APA séptima edición.",
         "Docente: Ing. Carlos Torres. Semestre 2026-2."],
        ["Guía de clase semana {n}", "Asignatura: {mat}", "Objetivo de aprendizaje de la sesión",
         "Lectura previa obligatoria y quiz en el aula virtual.", "Actividad en grupos de tres estudiantes.",
         "Parcial del corte programado para el {d} de {m}."],
        ["Tarea {n}: {mat}", "Enunciado del ejercicio", "Entregable: documento PDF y código fuente",
         "Calificación: 30% del segundo corte", "Plagio será sancionado según el reglamento estudiantil."],
    ],
    "Informes": [
        ["Informe de avance de obra No. {n}", "Proyecto: {p}", "Elaboró: {per}",
         "Avance físico acumulado: {pct}%.", "Actividades ejecutadas en el periodo: excavación, conformación de base y {it}.",
         "Novedades: lluvias afectaron el rendimiento de la cuadrilla.", "Recomendaciones y próximos pasos."],
        ["Informe técnico de interventoría", "Contrato de obra del proyecto {p}",
         "Se verificó la calidad del {it} mediante ensayos de laboratorio.", "Hallazgos y no conformidades",
         "Registro fotográfico adjunto.", "Conclusión: el contratista cumple parcialmente las especificaciones."],
        ["Informe mensual de gestión - {m}", "Área: residencia de obra", "Indicadores del periodo",
         "Accidentes reportados: 0. Personal en obra: {n}.", "Estado de maquinaria y equipos.",
         "Se presenta a la gerencia para su conocimiento."],
        ["Informe de inspección de seguridad industrial", "Frente de trabajo {p}",
         "Uso de EPP verificado en {pct}% del personal.", "Observaciones del SG-SST", "Acciones correctivas propuestas."],
    ],
    "Facturas": [
        ["FACTURA ELECTRÓNICA DE VENTA No. FE-{n}{d}", "Vendedor: {prov} NIT 900.{n}{d}.321-1",
         "Adquiriente: Constructora Vichada S.A.S. NIT 901.234.567-8", "Descripción: {it} cantidad {n}",
         "Subtotal {v}", "IVA 19%", "Total a pagar {v}", "CUFE: validado por la DIAN", "Forma de pago: crédito 30 días"],
        ["Comprobante de pago", "Beneficiario: {prov}", "Concepto: suministro de {it}",
         "Valor pagado: {v}", "Fecha de transacción: {d}/{m}/2026", "Número de aprobación {n}{d}{n}"],
        ["Cuenta de cobro No. {n}", "Señores Constructora Vichada S.A.S.", "Debe a: {per}",
         "La suma de {v} por concepto de {it}.", "Retención en la fuente aplicada.", "Firma y cédula"],
        ["Recibo de caja menor No. {n}", "Pagado a: {prov}", "Por concepto de {it} y {it2}",
         "Valor: {v}", "Aprobado por: {per}"],
    ],
    "Contratos": [
        ["CONTRATO DE OBRA No. {n}-2026", "Entre Constructora Vichada S.A.S., EL CONTRATANTE, y {prov}, EL CONTRATISTA",
         "CLÁUSULA PRIMERA - OBJETO: ejecutar las obras de {p}.", "CLÁUSULA SEGUNDA - VALOR: {v}.",
         "CLÁUSULA TERCERA - PLAZO: {n} días calendario.", "CLÁUSULA CUARTA - PÓLIZAS de cumplimiento y estabilidad.",
         "Las partes firman en Villavicencio."],
        ["CONTRATO DE PRESTACIÓN DE SERVICIOS", "Contratista: {per}", "Obligaciones del contratista",
         "Confidencialidad y propiedad intelectual", "Terminación anticipada por incumplimiento",
         "Cláusula penal pecuniaria", "Domicilio contractual: Villavicencio, Meta."],
        ["OTROSÍ No. {n} al contrato de suministro", "Las partes acuerdan modificar la cláusula de valor",
         "Se adiciona el suministro de {it}.", "Las demás cláusulas permanecen vigentes.", "Firma del representante legal"],
        ["ACUERDO DE CONFIDENCIALIDAD", "Parte reveladora y parte receptora", "Información confidencial del proyecto {p}",
         "Vigencia de {n} meses.", "Ley aplicable: República de Colombia.", "Resolución de controversias."],
    ],
    "Reuniones": [
        ["ACTA DE REUNIÓN No. {n}", "Fecha: {d} de {m} de 2026", "Asistentes: {per}, residente de obra, interventoría",
         "Orden del día", "1. Verificación del quórum", "2. Revisión de compromisos anteriores",
         "Desarrollo de la reunión", "Compromisos: responsable y fecha", "Siguiente reunión programada."],
        ["Acta de comité de obra semanal", "Proyecto {p}", "Temas tratados: avance, seguridad y {it}",
         "Decisiones tomadas por el comité", "Tareas pendientes asignadas a {per}", "Se levanta la sesión a las 5:00 p.m."],
        ["Convocatoria a reunión", "Se cita a los integrantes del comité el {d} de {m}",
         "Lugar: oficina central o enlace virtual de Teams", "Agenda propuesta", "Confirmar asistencia."],
        ["Minuta de reunión con proveedor {prov}", "Participantes", "Acuerdos sobre entregas de {it}",
         "Compromisos y responsables", "Próximo seguimiento."],
    ],
    "Presentaciones": [
        ["Presentación del proyecto {p}", "Diapositiva 1: Contexto", "Diapositiva 2: Objetivos",
         "Diapositiva 3: Cronograma", "Diapositiva 4: Resultados esperados", "Gracias - Preguntas"],
        ["Sustentación {mat}", "Agenda", "Problema", "Solución propuesta", "Demostración", "Conclusiones", "Gracias"],
        ["Capacitación: uso seguro de maquinaria", "Módulo {n}", "Riesgos principales", "Buenas prácticas",
         "Video de apoyo", "Evaluación final"],
        ["Pitch comercial Constructora Vichada", "Quiénes somos", "Proyectos destacados", "Clientes",
         "Propuesta de valor", "Contacto"],
    ],
    "Financiero": [
        ["PRESUPUESTO DE OBRA", "Proyecto: {p}", "Ítem | Unidad | Cantidad | Valor unitario | Valor total",
         "{it} | m3 | {n} | {v}", "{it2} | un | {n} | {v}", "Costos directos", "AIU 25%", "Valor total del presupuesto {v}"],
        ["Estado de resultados - {m} 2026", "Ingresos operacionales {v}", "Costos de ventas {v}",
         "Utilidad bruta", "Gastos administrativos", "Utilidad neta del periodo", "EBITDA"],
        ["Flujo de caja proyectado", "Saldo inicial {v}", "Ingresos por actas de obra", "Egresos por nómina y proveedores",
         "Saldo final proyectado", "Necesidad de financiación bancaria"],
        ["Reporte financiero trimestral", "Balance general", "Activos corrientes {v}", "Pasivos {v}",
         "Patrimonio", "Indicadores de liquidez y endeudamiento {pct}%"],
    ],
    "Otros": [
        ["Menú del almuerzo de la semana", "Lunes: sancocho", "Martes: carne asada", "Miércoles: pescado",
         "Precio por almuerzo {v}"],
        ["Cumpleaños del mes de {m}", "Felicitamos a {per}", "Celebración en la oficina el viernes"],
        ["Horario de buses de la ruta de personal", "Salida 5:30 a.m. desde el parque principal",
         "Regreso 6:00 p.m.", "Favor ser puntuales"],
        ["Lista de mercado", "arroz, aceite, huevos, café", "Recordar comprar pilas"],
        ["Chiste del día y meme del grupo", "Feliz fin de semana a todos", "Buen viaje {per}"],
        ["Clasificados: se vende moto", "Modelo 2019, papeles al día", "Precio negociable {v}", "Llamar al 310 555 {n}{d}"],
    ],
}

# Formato preferido por categoría (probabilidades), el resto se mezcla
FORMATS = ["pdf", "docx", "xlsx", "pptx", "txt"]
FORMAT_BIAS = {
    "Presentaciones": [0.15, 0.05, 0.0, 0.75, 0.05],
    "Financiero": [0.35, 0.15, 0.4, 0.05, 0.05],
    "Facturas": [0.7, 0.1, 0.1, 0.0, 0.1],
    "Contratos": [0.5, 0.45, 0.0, 0.0, 0.05],
}
DEFAULT_BIAS = [0.45, 0.35, 0.05, 0.05, 0.10]


FORMAT_BIAS.update(FORMAT_BIAS_JURIDICO)
PROFILE_TEMPLATES = {"general": (TEMPLATES, COMUNES), "juridico": (TEMPLATES_JURIDICO, COMUNES_JURIDICO)}


def generate_text(category: str, rng: random.Random) -> str:
    templates, comunes = PROFILE_TEMPLATES.get(PROFILE, (TEMPLATES, COMUNES))
    if category not in templates:  # p.ej. textos de relleno de las muestras de seguridad
        templates, comunes = TEMPLATES, COMUNES
        if category not in templates:
            category = _r(rng, list(templates))
    tpl = _r(rng, templates[category])
    ctx = _ctx(rng)
    if templates is TEMPLATES_JURIDICO:
        ctx |= juridico_ctx(rng)
    lines = [l.format(**ctx) for l in tpl]
    # Documentos reales son incompletos: a veces falta el título y solo quedan 2-4 líneas
    keep_title = rng.random() < 0.6
    body = lines[1:]
    rng.shuffle(body)
    lines = ([lines[0]] if keep_title else []) + body[:rng.randint(2, 4)]
    for _ in range(rng.randint(1, 3)):
        lines.insert(rng.randint(0, len(lines)), _r(rng, comunes).format(**ctx))
    # "Contaminación": los documentos mezclan temas (un acta habla del contrato, un informe del presupuesto)
    if rng.random() < 0.6:
        for _ in range(rng.randint(1, 2)):
            other = _r(rng, [c for c in templates if c != category])
            lines.append(_r(rng, _r(rng, templates[other])).format(**ctx))
    return "\n".join(lines)


# ------------------------------------------------------------ escritura de archivos
def to_pdf(text: str) -> bytes:
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=10)
    return doc.tobytes()


def to_docx(text: str) -> bytes:
    import docx
    d = docx.Document()
    for line in text.splitlines():
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def to_xlsx(text: str) -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    for line in text.splitlines():
        ws.append([c.strip() for c in line.split("|")])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def to_pptx(text: str) -> bytes:
    import pptx
    from pptx.util import Inches
    prs = pptx.Presentation()
    lines = text.splitlines()
    for i in range(0, len(lines), 3):
        s = prs.slides.add_slide(prs.slide_layouts[5])
        s.shapes.title.text = lines[i]
        if lines[i + 1:i + 3]:
            tb = s.shapes.add_textbox(Inches(1), Inches(2), Inches(8), Inches(3))
            tb.text_frame.text = "\n".join(lines[i + 1:i + 3])
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


WRITERS = {"pdf": to_pdf, "docx": to_docx, "xlsx": to_xlsx, "pptx": to_pptx,
           "txt": lambda t: t.encode("utf-8")}


def render(text: str, fmt: str) -> bytes:
    return WRITERS[fmt](text)


def generate_topic_dataset(out_dir: Path, per_class: int = 90, seed: int = 42,
                           label_noise: float = 0.03) -> list[tuple[Path, str]]:
    """``label_noise`` simula errores del etiquetado manual (documentados en el informe)."""
    if PROFILE not in PROFILE_TEMPLATES:  # perfil con documentos reales únicamente (data/dataset_real)
        return []
    rng = random.Random(seed)
    out_dir = Path(out_dir)
    items = []
    for cat in CATEGORIES:
        (out_dir / cat).mkdir(parents=True, exist_ok=True)
        for i in range(per_class):
            text = generate_text(cat, rng)
            fmt = rng.choices(FORMATS, FORMAT_BIAS.get(cat, DEFAULT_BIAS))[0]
            p = out_dir / cat / f"{cat.lower()}_{i:03d}.{fmt}"
            p.write_bytes(render(text, fmt))
            label = cat if rng.random() >= label_noise else _r(rng, CATEGORIES)
            items.append((p, label))
    return items
