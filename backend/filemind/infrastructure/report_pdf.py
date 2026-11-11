"""Reporte PDF del análisis de un archivo (para descargar, imprimir o enviar).

Se arma con HTML + ``pymupdf.Story`` (PyMuPDF ya es dependencia del proyecto), así
no hace falta instalar nada más. El reporte resume lo que vio cada fase del protocolo,
el puntaje de riesgo, la clasificación de la IA con las palabras que más pesaron y la
traza de eventos con marca de tiempo.
"""
from __future__ import annotations

import html
import io
from datetime import datetime
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:  # versiones antiguas de PyMuPDF
    import fitz

from ..config import ROOT

LOGO_DIR = ROOT.parent / "frontend" / "public"
ACCENT = "#ea6a12"
STATUS = {"clasificado": "Clasificado y guardado", "cuarentena": "En cuarentena cifrada",
          "duplicado": "Duplicado", "eliminado": "Eliminado de la cuarentena"}
LEVEL = {"bajo": ("Bajo", "#15803d"), "medio": ("Medio", "#b45309"), "alto": ("Alto", "#c42f2f")}
CTRL = {"ok": ("Sin hallazgos", "#15803d"), "aviso": ("Aviso", "#b45309"), "alerta": ("Alerta", "#c42f2f"),
        "no_aplica": ("No aplica", "#6b7280")}

CSS = f"""
* {{ font-family: sans-serif; }}
body {{ font-size: 9.5pt; color: #1f2328; }}
h1 {{ font-size: 17pt; margin: 0 0 2pt 0; }}
h2 {{ font-size: 11.5pt; color: {ACCENT}; margin: 12pt 0 4pt 0; border-bottom: 0.6pt solid #e5e7eb; padding-bottom: 2pt; }}
.muted {{ color: #6b7280; }}
.small {{ font-size: 8pt; }}
table {{ width: 100%; border-collapse: collapse; }}
td, th {{ padding: 3pt 4pt; vertical-align: top; border-bottom: 0.4pt solid #eceef1; text-align: left; }}
th {{ color: #6b7280; font-size: 7.5pt; text-transform: uppercase; }}
.k {{ width: 28%; color: #6b7280; }}
.big {{ font-size: 20pt; font-weight: bold; }}
.kv {{ margin: 0 0 5pt 0; }}
.mono {{ font-family: monospace; font-size: 7.5pt; }}
"""


from ..domain.models import CATEGORY_LABELS as CATEGORY_LABEL  # noqa: E402  (mismos nombres que la interfaz)


def cat_label(c: str | None) -> str:
    return CATEGORY_LABEL.get(c, c or "—")


def _e(x) -> str:
    return html.escape(str(x if x is not None else "—"))


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%d/%m/%Y %H:%M:%S")
    except ValueError:
        return iso


def _size(n) -> str:
    if not n:
        return "—"
    return f"{n / 1024:.1f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.2f} MB"


def build_html(rec: dict, events: list[dict], user: str | None = None) -> str:
    rep = rec.get("report") or {}
    risk = rep.get("risk") or {}
    lvl_txt, lvl_col = LEVEL.get(rec.get("risk_level"), ("—", "#6b7280"))
    has_logo = (LOGO_DIR / "ucc-logo.png").exists()
    parts = [f"""
<table><tr>
  <td style="border:0;padding:0"><span style="font-size:20pt;font-weight:bold">File<span style="color:{ACCENT}">Mind</span></span><br/>
    <span class="muted">Reporte de análisis de seguridad y clasificación</span></td>
  <td style="border:0;padding:0;text-align:right">{'<img src="ucc-logo.png" width="130"/>' if has_logo else ''}<br/>
    <span class="small muted">Proyecto académico · Universidad Cooperativa de Colombia</span></td>
</tr></table>
<h1 style="margin-top:12pt">{_e(rec.get('original_name'))}</h1>
<p class="muted">Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')}{f' por {_e(user)}' if user else ''}</p>

<table>
<tr><th>Resultado</th><th>Puntaje de riesgo</th><th>Categoría</th></tr>
<tr>
  <td style="border:0"><b style="font-size:12pt">{_e(STATUS.get(rec.get('status'), rec.get('status')))}</b></td>
  <td style="border:0"><span class="big" style="color:{lvl_col}">{_e(rec.get('risk_score'))}</span><span class="muted"> / 100 · {lvl_txt}</span></td>
  <td style="border:0"><b style="font-size:12pt">{_e(cat_label(rec['category']) if rec.get('category') else 'Sin clasificar')}</b>
    {f'<br/><span class="small muted">confianza {rec["category_confidence"] * 100:.0f} %</span>' if rec.get('category_confidence') else ''}</td>
</tr></table>

<h2>Datos del archivo</h2>
<table>
<tr><td class="k">Chat de origen</td><td>{_e(rec.get('group_name'))}</td></tr>
<tr><td class="k">Remitente</td><td>{_e(rec.get('sender'))}</td></tr>
<tr><td class="k">Recibido</td><td>{_fmt_date(rec.get('detected_at'))}</td></tr>
<tr><td class="k">Tamaño · tipo real</td><td>{_size(rec.get('size'))} · {_e(rec.get('real_type'))}</td></tr>
<tr><td class="k">Huella SHA-256</td><td class="mono">{_e(rec.get('sha256'))}</td></tr>
<tr><td class="k">Tiempo del protocolo</td><td>{_e(rec.get('protocol_seconds'))} s (límite 15 s)</td></tr>
</table>
"""]
    reasons = rec.get("reasons") or []
    if rec.get("notification") or reasons:
        parts.append("<h2>Qué encontró FileMind</h2>")
        if reasons:
            parts.append("<ul>" + "".join(f"<li>{_e(r)}</li>" for r in reasons) + "</ul>")
        if rec.get("notification"):
            parts.append(f"<p>{_e(rec['notification']).replace(chr(10), '<br/>')}</p>")

    controls = rep.get("controls") or []
    if controls:
        rows = []
        for c in controls:
            t, col = CTRL.get(c.get("estado"), (c.get("estado"), "#6b7280"))
            rows.append(f"<tr><td>{_e(c.get('fase'))}</td><td><b>{_e(c.get('nombre'))}</b><br/>"
                        f"<span class='small muted'>{_e(c.get('resumen'))}</span></td>"
                        f"<td style='color:{col}'>{t}</td><td style='text-align:right'>{_e(c.get('puntos', 0))}</td></tr>")
        parts.append("<h2>Controles de ciberseguridad</h2><table><tr><th>Fase</th><th>Control</th><th>Resultado</th>"
                     "<th style='text-align:right'>Puntos</th></tr>" + "".join(rows) + "</table>")

    if risk:
        ml = risk.get("ml_probabilities") or {}
        contrib = ", ".join(f"{_e(k)} (+{v})" for k, v in (risk.get("rule_contributions") or [])) or "ninguna"
        parts.append(f"""<h2>Cómo se calculó el puntaje (fase 4)</h2>
<p class="kv"><span class="small muted">Reglas que sumaron</span><br/>{contrib}</p>
<p class="kv"><span class="small muted">Puntaje por reglas</span><br/>{_e(risk.get('rule_score'))}</p>
<p class="kv"><span class="small muted">Modelo de riesgo (IA)</span><br/>{' · '.join(f'{_e(k)} {v * 100:.1f} %' for k, v in ml.items()) or '—'}</p>
<p class="kv"><span class="small muted">Tipo de amenaza</span><br/>{_e(risk.get('threat_type') or 'ninguna')}</p>""")

    topic = rep.get("topic") or {}
    if topic:
        top = " · ".join(f"{_e(cat_label(c))} {p * 100:.0f} %" for c, p in topic.get("top", []))
        words = ", ".join(f"«{_e(w['termino'])}» ({w['porcentaje']} %)" for w in topic.get("explicacion", [])) or "—"
        parts.append(f"""<h2>Clasificación con IA</h2>
<p class="kv"><span class="small muted">Categorías más probables</span><br/>{top}</p>
<p class="kv"><span class="small muted">Palabras que más pesaron</span><br/>{words}</p>
<p class="kv"><span class="small muted">¿Necesita revisión?</span><br/>{'Sí, la confianza fue baja' if topic.get('needs_review') else 'No'}</p>""")

    if events:
        rows = "".join(f"<tr><td class='mono'>{_fmt_date(e['ts'])}</td><td>{_e(e['event'].replace('_', ' '))}</td></tr>"
                       for e in sorted(events, key=lambda e: e["ts"])[:40])
        parts.append(f"<h2>Traza de auditoría</h2><table><tr><th>Fecha y hora</th><th>Evento</th></tr>{rows}</table>")

    parts.append("<p class='small muted' style='margin-top:14pt'>FileMind no reemplaza un antivirus empresarial. "
                 "Este reporte se generó automáticamente a partir del registro de auditoría (RNF8).</p>")
    return "".join(parts)


def render_pdf(rec: dict, events: list[dict], user: str | None = None) -> bytes:
    story = fitz.Story(html=build_html(rec, events, user), user_css=CSS,
                       archive=fitz.Archive(str(LOGO_DIR)) if LOGO_DIR.exists() else None)
    buf = io.BytesIO()
    writer = fitz.DocumentWriter(buf)
    page = fitz.paper_rect("a4")
    where = page + (42, 42, -42, -48)
    more = True
    while more:
        dev = writer.begin_page(page)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    # Pie con número de página
    doc = fitz.open("pdf", buf.getvalue())
    for i, p in enumerate(doc):
        p.insert_text((42, p.rect.height - 24), f"FileMind · {rec.get('original_name', '')[:70]} · página {i + 1} de {len(doc)}",
                      fontsize=7, color=(0.45, 0.45, 0.5))
    return doc.tobytes(deflate=True)


def report_filename(rec: dict) -> str:
    stem = Path(rec.get("original_name") or "archivo").stem[:60]
    return f"FileMind_reporte_{stem}.pdf"
