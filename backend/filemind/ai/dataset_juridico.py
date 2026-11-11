"""Plantillas del dataset sintético para el perfil "juridico" (bufete de abogados).

Mismo enfoque que ``dataset.py``: documentos cortos e incompletos, con
vocabulario compartido entre categorías (una tutela cita una petición, un
recurso cita la sentencia, una contestación habla del poder) para que la
tarea no sea trivial. Los documentos reales anonimizados del bufete se
añaden en ``data/dataset_real/<Categoria>/`` y se mezclan al entrenar.
"""
from __future__ import annotations

import random

JUZGADOS = ["Juzgado Tercero Civil del Circuito de Villavicencio", "Juzgado Segundo Laboral del Circuito de Bogotá",
            "Juzgado Quinto Civil Municipal de Villavicencio", "Juzgado Primero de Familia de Villavicencio",
            "Juzgado Once Administrativo de Bogotá", "Tribunal Superior del Distrito Judicial de Villavicencio",
            "Juzgado Promiscuo Municipal de Puerto López", "Juzgado Cuarto de Pequeñas Causas Laborales de Bogotá"]
CIUDADES = ["Villavicencio", "Bogotá D.C.", "Acacías", "Puerto López", "Granada", "Puerto Gaitán"]
ABOGADOS = ["Dra. Paola Suárez Ríos", "Dr. Andrés Felipe Pardo", "Dra. Diana Moreno Castro",
            "Dr. Nelson Quiroga León", "Dra. Laura Méndez Rojas", "Dr. Miguel Colmenares"]
CLIENTES = ["María Fernanda López", "Jorge Enrique Useche", "Inversiones del Llano S.A.S.",
            "Luis Alberto Garzón", "Transportes Vichada Ltda.", "Rosa Elvira Martínez", "Agropecuaria La Esperanza S.A.S."]
CONTRAPARTES = ["Banco Agrario de Colombia S.A.", "Nueva EPS S.A.", "Colpensiones", "Constructora Andina S.A.S.",
                "Carlos Arturo Rincón", "Aseguradora Solidaria de Colombia", "Municipio de Villavicencio"]
PROCESOS = ["proceso verbal de responsabilidad civil contractual", "proceso ejecutivo singular",
            "proceso ordinario laboral de primera instancia", "proceso de restitución de inmueble arrendado",
            "proceso de divorcio contencioso", "proceso de reparación directa", "proceso verbal sumario",
            "proceso de pertenencia por prescripción adquisitiva"]
DERECHOS = ["salud", "petición", "debido proceso", "mínimo vital", "seguridad social", "trabajo", "vivienda digna"]
NORMAS = ["artículo 82 del Código General del Proceso", "artículo 86 de la Constitución Política",
          "Decreto 2591 de 1991", "Ley 1755 de 2015", "artículo 96 del C.G.P.", "Ley 640 de 2001",
          "artículo 318 del C.G.P.", "artículo 320 del C.G.P.", "Código Sustantivo del Trabajo"]


def juridico_ctx(rng: random.Random) -> dict:
    return {"juz": rng.choice(JUZGADOS), "ciu": rng.choice(CIUDADES), "abg": rng.choice(ABOGADOS),
            "cli": rng.choice(CLIENTES), "dem": rng.choice(CONTRAPARTES), "proc": rng.choice(PROCESOS),
            "der": rng.choice(DERECHOS), "ley": rng.choice(NORMAS), "tp": rng.randint(80_000, 390_000),
            "cc": f"{rng.randint(17_000_000, 1_120_000_000):,}".replace(",", "."),
            "rad": f"50001-31-03-00{rng.randint(1, 9)}-2026-00{rng.randint(100, 999)}-00"}


COMUNES_JURIDICO = [
    "Señor Juez, respetuosamente.", "Cordialmente,", "Atentamente,", "{ciu}, {d} de {m} de 2026.",
    "Radicado: {rad}", "Referencia: {proc}", "Demandante: {cli}. Demandado: {dem}.",
    "Se adjunta en formato PDF para su radicación.", "Enviado desde el grupo del caso {cli}.",
    "Notificaciones: correo electrónico registrado en el SIRNA.", "Revisar antes de radicar, por favor.",
    "Anexo lo solicitado por la doctora.", "{abg}, T.P. {tp} del C.S. de la J.",
]

TEMPLATES_JURIDICO: dict[str, list[list[str]]] = {
    "Demandas": [
        ["DEMANDA", "Señor {juz}, E.S.D.", "{abg}, mayor de edad, identificada con C.C. {cc}, obrando como apoderada de {cli},",
         "presento DEMANDA de {proc} contra {dem}.", "I. HECHOS", "PRIMERO: El {d} de {m} de 2025 las partes celebraron contrato.",
         "II. PRETENSIONES", "Que se declare civilmente responsable a {dem} y se condene al pago de {v}.",
         "III. FUNDAMENTOS DE DERECHO: {ley}.", "IV. CUANTÍA: estimo la cuantía en {v}.", "V. JURAMENTO ESTIMATORIO"],
        ["DEMANDA EJECUTIVA SINGULAR DE MAYOR CUANTÍA", "Ejecutante: {cli}", "Ejecutado: {dem}",
         "Título ejecutivo: pagaré No. {n} por valor de {v}.", "Solicito librar mandamiento de pago por el capital y los intereses moratorios.",
         "MEDIDAS CAUTELARES: embargo y secuestro de bienes del ejecutado.", "Competencia: por el domicilio del demandado y la cuantía."],
        ["DEMANDA ORDINARIA LABORAL DE PRIMERA INSTANCIA", "Demandante: {cli}", "Demandado: {dem}",
         "HECHOS: el demandante laboró desde el {d} de {m} de 2019 sin afiliación a seguridad social.",
         "PRETENSIONES: reconocimiento del contrato realidad, cesantías, primas, vacaciones e indemnización moratoria.",
         "PRUEBAS: documentales y testimoniales.", "Fundamento: {ley}."],
        ["SUBSANACIÓN DE DEMANDA", "Radicado {rad}", "Dentro del término concedido en el auto inadmisorio, subsano la demanda así:",
         "1. Se aclara el acápite de pretensiones.", "2. Se allega el poder con presentación personal.",
         "3. Se indica el canal digital del demandado conforme a la Ley 2213 de 2022."],
        ["REFORMA DE LA DEMANDA", "Proceso: {proc}", "Conforme al artículo 93 del C.G.P. reformo la demanda",
         "Se adicionan los hechos décimo y undécimo.", "Se incluye como pretensión subsidiaria el pago de {v}.",
         "Se integra la demanda en un solo escrito."],
    ],
    "Contestaciones": [
        ["CONTESTACIÓN DE LA DEMANDA", "Señor {juz}", "Radicado: {rad}", "{abg}, apoderado de {dem}, contesto la demanda así:",
         "FRENTE A LOS HECHOS: el primero es cierto; el segundo no es cierto; el tercero no me consta.",
         "FRENTE A LAS PRETENSIONES: me opongo a todas y cada una de ellas.",
         "EXCEPCIONES DE MÉRITO: inexistencia de la obligación, prescripción, cobro de lo no debido."],
        ["EXCEPCIONES PREVIAS", "Proceso {proc}", "Propongo las siguientes excepciones previas del artículo 100 del C.G.P.:",
         "1. Falta de jurisdicción o competencia.", "2. Ineptitud de la demanda por falta de requisitos formales.",
         "3. No comprender la demanda a todos los litisconsortes necesarios.", "Solicito se declaren probadas y se termine el proceso."],
        ["DEMANDA DE RECONVENCIÓN", "Demandante en reconvención: {dem}", "Demandado en reconvención: {cli}",
         "Dentro del término de traslado presento demanda de reconvención.", "PRETENSIONES: que se declare el incumplimiento del contrato por parte de {cli}.",
         "Cuantía: {v}."],
        ["CONTESTACIÓN DE DEMANDA LABORAL", "Demandado: {dem}", "Me pronuncio sobre los hechos:",
         "Se niega la existencia de subordinación; el demandante prestó servicios independientes.",
         "EXCEPCIONES: buena fe, compensación, prescripción trienal.", "Se aporta el contrato de prestación de servicios."],
    ],
    "Tutelas": [
        ["ACCIÓN DE TUTELA", "Señor Juez (Reparto)", "Accionante: {cli}", "Accionada: {dem}",
         "Derecho fundamental vulnerado: {der}.", "HECHOS: la accionada no ha autorizado el procedimiento ordenado por el médico tratante.",
         "PRETENSIÓN: que se ordene a {dem} en el término de 48 horas autorizar y practicar lo requerido.",
         "Fundamento: {ley}.", "JURAMENTO: no he presentado otra tutela por los mismos hechos."],
        ["IMPUGNACIÓN DEL FALLO DE TUTELA", "Radicado {rad}", "Impugno la sentencia de tutela proferida el {d} de {m}",
         "El juez de primera instancia declaró improcedente la acción desconociendo el perjuicio irremediable.",
         "Solicito revocar el fallo y en su lugar amparar el derecho a la {der}."],
        ["INCIDENTE DE DESACATO", "Accionante: {cli}", "Accionada: {dem}",
         "La entidad no ha cumplido la orden de tutela dentro del término.", "Solicito abrir incidente de desacato y sancionar al responsable.",
         "Artículos 27 y 52 del Decreto 2591 de 1991."],
        ["ACCIÓN DE TUTELA POR DERECHO DE PETICIÓN", "Accionante: {cli}", "El {d} de {m} radiqué derecho de petición ante {dem}",
         "Han transcurrido más de quince días hábiles sin respuesta de fondo.", "Solicito tutelar el derecho fundamental de petición.",
         "Anexo copia de la petición con sello de radicado."],
    ],
    "Peticiones": [
        ["DERECHO DE PETICIÓN", "Señores {dem}", "Asunto: derecho de petición de interés particular",
         "{cli}, identificado con C.C. {cc}, en ejercicio del artículo 23 de la Constitución y la Ley 1755 de 2015,",
         "solicito: 1. Copia de la historia laboral completa. 2. Certificación de aportes.",
         "Recibiré respuesta en el correo electrónico indicado.", "Término de respuesta: quince días hábiles."],
        ["RESPUESTA A DERECHO DE PETICIÓN", "Radicado de entrada No. {n}{d}", "Señor(a) {cli}",
         "En atención a su solicitud, nos permitimos informar lo siguiente:", "Se remite la certificación solicitada.",
         "Contra esta decisión no procede recurso.", "Atentamente, Oficina de Atención al Ciudadano."],
        ["SOLICITUD DE INFORMACIÓN Y DOCUMENTOS", "Destinatario: {dem}", "Con fundamento en la Ley 1755 de 2015",
         "solicito copia del expediente administrativo y de los actos que resolvieron la reclamación.",
         "Petición de documentos: término de diez días.", "Firma del peticionario."],
        ["RECLAMACIÓN ADMINISTRATIVA", "Señores {dem}", "Reclamo el reconocimiento y pago de la pensión de vejez",
         "El afiliado cumple los requisitos de edad y semanas cotizadas.", "Agotamiento de la reclamación previa del artículo 6 del C.P.T.",
         "Anexos: cédula, historia laboral."],
    ],
    "Recursos": [
        ["RECURSO DE REPOSICIÓN Y EN SUBSIDIO APELACIÓN", "Radicado {rad}", "Contra el auto del {d} de {m} de 2026",
         "interpongo recurso de reposición y en subsidio de apelación conforme al artículo 318 y 320 del C.G.P.",
         "SUSTENTACIÓN: el despacho erró al negar la medida cautelar.", "PETICIÓN: revocar el auto recurrido."],
        ["SUSTENTACIÓN DEL RECURSO DE APELACIÓN", "Tribunal Superior - Sala Civil", "Apelante: {cli}",
         "Reparos concretos contra la sentencia de primera instancia:", "1. Indebida valoración probatoria.",
         "2. Aplicación indebida de la norma sustancial.", "Solicito revocar la sentencia y acceder a las pretensiones."],
        ["RECURSO DE QUEJA", "Proceso {proc}", "El juzgado negó la concesión del recurso de apelación",
         "Interpongo recurso de queja ante el superior.", "Solicito copias de las piezas procesales pertinentes."],
        ["ALEGATOS DE CONCLUSIÓN", "Señor {juz}", "Radicado {rad}", "Presento alegatos de conclusión:",
         "Quedó demostrado con las pruebas practicadas el incumplimiento de {dem}.",
         "Solicito dictar sentencia favorable a las pretensiones."],
        ["DEMANDA DE CASACIÓN", "Corte Suprema de Justicia - Sala de Casación", "Recurrente: {cli}",
         "Cargo primero: violación directa de la ley sustancial.", "Cargo segundo: error de hecho en la apreciación de pruebas."],
    ],
    "Providencias": [
        ["{juz}", "SENTENCIA No. {n}", "{ciu}, {d} de {m} de 2026", "Proceso: {proc}. Radicado {rad}.",
         "I. ANTECEDENTES", "II. CONSIDERACIONES", "III. DECISIÓN: En mérito de lo expuesto, el Juzgado, administrando justicia en nombre de la República",
         "RESUELVE: PRIMERO. Declarar probadas las pretensiones. SEGUNDO. Condenar en costas a la parte vencida.",
         "NOTIFÍQUESE Y CÚMPLASE. El Juez."],
        ["AUTO ADMISORIO DE LA DEMANDA", "{juz}", "Radicado {rad}", "Por reunir los requisitos del artículo 82 del C.G.P.,",
         "RESUELVE: Admitir la demanda. Notificar al demandado. Correr traslado por veinte días.",
         "Reconocer personería al abogado {abg}.", "NOTIFÍQUESE."],
        ["AUTO INADMISORIO", "{juz}", "Inadmite la demanda para que en cinco días se subsane:",
         "1. Aportar el poder conferido en debida forma.", "2. Acreditar el envío de la demanda al demandado.",
         "So pena de rechazo."],
        ["NOTIFICACIÓN PERSONAL", "Señor(a) {dem}", "Se le notifica el auto admisorio dentro del proceso {rad}",
         "conforme al artículo 8 de la Ley 2213 de 2022.", "Se entenderá notificado dos días hábiles después del envío."],
        ["FALLO DE TUTELA", "{juz}", "Accionante: {cli}. Accionada: {dem}.", "RESUELVE: TUTELAR el derecho fundamental a la {der}.",
         "ORDENAR a la accionada que en 48 horas cumpla lo dispuesto.", "Comuníquese por el medio más expedito."],
        ["ESTADO ELECTRÓNICO No. {n}", "{juz}", "Fecha de fijación: {d} de {m}", "Radicado {rad} - Auto que fija fecha de audiencia inicial."],
    ],
    "Poderes": [
        ["PODER ESPECIAL", "Señor {juz}", "{cli}, mayor de edad, identificado con C.C. {cc},",
         "confiero poder especial, amplio y suficiente a {abg}, T.P. {tp} del C.S. de la J.,",
         "para que en mi nombre inicie y lleve hasta su terminación {proc} contra {dem}.",
         "Mi apoderado queda facultado para recibir, conciliar, transigir, desistir, sustituir y reasumir.",
         "Acepto, {abg}."],
        ["PODER GENERAL - ESCRITURA PÚBLICA", "Notaría Segunda de {ciu}", "El poderdante {cli} otorga poder general",
         "para representarlo ante autoridades judiciales y administrativas.", "Vigencia indefinida hasta su revocatoria."],
        ["SUSTITUCIÓN DE PODER", "Radicado {rad}", "{abg}, apoderado de {cli}, sustituyo el poder a mí conferido",
         "en favor del abogado Dr. Julián Torres, T.P. {tp}, con las mismas facultades.", "Me reservo la facultad de reasumir."],
        ["REVOCATORIA DE PODER", "Señor Juez", "{cli} revoca el poder otorgado a {abg}",
         "y solicita reconocer personería al nuevo apoderado.", "Paz y salvo de honorarios anexo."],
        ["PODER PARA CONCILIAR", "Centro de Conciliación de la Cámara de Comercio de {ciu}",
         "Otorgo poder a {abg} para asistir a la audiencia de conciliación y conciliar hasta por {v}."],
    ],
    "Contratos": [
        ["CONTRATO DE PRESTACIÓN DE SERVICIOS PROFESIONALES DE ABOGADO", "Entre {cli}, EL CLIENTE, y {abg}, EL ABOGADO",
         "OBJETO: representación judicial en el {proc}.", "HONORARIOS: {v} más el 20% de lo obtenido (cuota litis).",
         "OBLIGACIONES DEL ABOGADO: actuar con diligencia y rendir informes.", "Firmado en {ciu} el {d} de {m} de 2026."],
        ["CONTRATO DE ARRENDAMIENTO DE LOCAL COMERCIAL", "Arrendador: {cli}. Arrendatario: {dem}.",
         "Canon mensual: {v}.", "Término: doce meses prorrogables.", "Cláusula penal por incumplimiento.",
         "El arrendatario renuncia a los requerimientos para constituirlo en mora."],
        ["CONTRATO DE COMPRAVENTA", "Vendedor: {cli}. Comprador: {dem}.", "Objeto: inmueble con matrícula inmobiliaria 230-{n}{d}.",
         "Precio: {v}.", "Saneamiento por evicción y vicios redhibitorios.", "Las partes firman ante notario."],
        ["PROMESA DE COMPRAVENTA", "Promitente vendedor {cli}", "Promitente comprador {dem}",
         "Las partes se obligan a celebrar el contrato prometido en la Notaría el {d} de {m}.", "Arras de retracto: {v}."],
        ["OTROSÍ No. {n}", "Las partes modifican la cláusula de plazo del contrato", "Las demás cláusulas permanecen vigentes."],
        ["ACUERDO DE CONFIDENCIALIDAD", "Parte reveladora: {cli}", "La información del caso es confidencial",
         "Vigencia: {n} meses.", "Ley aplicable: República de Colombia."],
    ],
    "Conciliaciones": [
        ["SOLICITUD DE CONCILIACIÓN EXTRAJUDICIAL EN DERECHO", "Centro de Conciliación", "Convocante: {cli}. Convocado: {dem}.",
         "HECHOS", "PRETENSIONES: pago de {v}.", "Requisito de procedibilidad de la Ley 640 de 2001 y Ley 2220 de 2022.",
         "Cuantía: {v}."],
        ["ACTA DE CONCILIACIÓN No. {n}", "En {ciu}, el {d} de {m} de 2026, comparecieron {cli} y {dem}",
         "ACUERDO: el convocado pagará {v} en {n} cuotas mensuales.", "El acta presta mérito ejecutivo y hace tránsito a cosa juzgada.",
         "Conciliador: {abg}."],
        ["CONSTANCIA DE NO ACUERDO", "Centro de Conciliación de la Procuraduría", "Las partes no llegaron a acuerdo",
         "Se entiende agotado el requisito de procedibilidad.", "Se expide constancia a solicitud del convocante."],
        ["CONSTANCIA DE INASISTENCIA", "Convocado {dem} no asistió a la audiencia", "No presentó excusa dentro de los tres días siguientes."],
        ["CITACIÓN A AUDIENCIA DE CONCILIACIÓN", "Señor(a) {dem}", "Se le cita a audiencia el {d} de {m} a las 9:00 a.m.",
         "Lugar: sede del centro o enlace virtual.", "Debe asistir personalmente o por medio de apoderado."],
    ],
    "Pruebas": [
        ["CERTIFICADO DE EXISTENCIA Y REPRESENTACIÓN LEGAL", "Cámara de Comercio de {ciu}", "Razón social: {dem}",
         "NIT 900.{n}{d}.321-1", "Representante legal: Carlos Arturo Rincón.", "Matrícula mercantil renovada 2026."],
        ["DICTAMEN PERICIAL", "Perito: Ing. Nelson Quiroga, contador público", "Objeto: cuantificar los perjuicios materiales",
         "Daño emergente: {v}. Lucro cesante: {v}.", "Metodología y fuentes consultadas.", "Declaración de imparcialidad del perito."],
        ["DECLARACIÓN EXTRAJUICIO", "Notaría Primera de {ciu}", "El declarante manifiesta bajo la gravedad del juramento",
         "que conoce a {cli} desde hace {n} años y le consta la convivencia.", "Se expide para fines judiciales."],
        ["HISTORIA CLÍNICA - EPICRISIS", "Paciente: {cli}", "Diagnóstico principal y plan de manejo",
         "Médico tratante ordena procedimiento quirúrgico.", "Incapacidad médica de {n} días."],
        ["CERTIFICADO DE TRADICIÓN Y LIBERTAD", "Oficina de Registro de Instrumentos Públicos de {ciu}",
         "Matrícula inmobiliaria 230-{n}{d}", "Anotación No. 3: compraventa.", "Anotación No. 4: embargo ejecutivo."],
        ["RELACIÓN DE PRUEBAS DOCUMENTALES", "1. Copia del contrato.", "2. Facturas y comprobantes de pago.",
         "3. Capturas de pantalla de conversaciones de WhatsApp.", "4. Correos electrónicos cruzados entre las partes.",
         "Testimonios: citar a los testigos."],
    ],
    "Honorarios": [
        ["CUENTA DE COBRO No. {n}", "Señor(a) {cli}", "Debe a: {abg}", "La suma de {v} por concepto de honorarios profesionales",
         "del {proc}, según contrato de prestación de servicios.", "Consignar en la cuenta de ahorros registrada."],
        ["FACTURA ELECTRÓNICA DE VENTA No. FE-{n}{d}", "Emisor: Suárez & Pardo Abogados S.A.S.", "Adquiriente: {cli}",
         "Servicio: asesoría y representación judicial", "Subtotal {v}", "IVA 19%", "Total {v}", "CUFE validado por la DIAN"],
        ["LIQUIDACIÓN DE HONORARIOS Y GASTOS DEL PROCESO", "Cliente: {cli}", "Honorarios pactados: {v}",
         "Gastos de notificación y copias: {v}", "Anticipo recibido: {v}", "Saldo pendiente: {v}"],
        ["PAZ Y SALVO", "{abg} certifica que {cli} se encuentra a paz y salvo", "por concepto de honorarios del proceso {rad}."],
        ["RECIBO DE PAGO DE HONORARIOS", "Recibí de {cli}", "la suma de {v}", "como abono a los honorarios pactados."],
    ],
    "Otros": [
        ["Menú del almuerzo de la semana", "Lunes: sancocho", "Martes: carne asada", "Precio por almuerzo {v}"],
        ["Cumpleaños del mes de {m}", "Felicitamos a {abg}", "Celebración en la oficina el viernes"],
        ["Turnos de aseo de la oficina", "Lunes y martes: recepción", "Recordar sacar la basura"],
        ["Lista de compras de papelería", "resmas de papel, tóner, carpetas AZ, ganchos legajadores"],
        ["Feliz fin de semana a todos", "Buen viaje doctora", "Meme del grupo de la oficina"],
        ["Clasificados: se vende carro", "Modelo 2018, papeles al día", "Precio negociable {v}"],
        ["Horario de atención de la oficina", "Lunes a viernes de 8:00 a.m. a 5:00 p.m.", "Sábados con cita previa"],
    ],
}

FORMAT_BIAS_JURIDICO = {
    "Honorarios": [0.6, 0.15, 0.2, 0.0, 0.05],
    "Pruebas": [0.75, 0.1, 0.05, 0.0, 0.1],
    "Providencias": [0.85, 0.1, 0.0, 0.0, 0.05],
}
