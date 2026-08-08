"""The shift report, as a PDF.

This is the document the outgoing controller hands over and the incoming one
reads before touching anything. It is built from the same briefing the Handover
tab shows, so the paper and the screen cannot disagree.

It answers two questions in that order, because that is the order the reader
needs them:

1. **What do I pick up first?** Never-opened reportings, open action-required
   work, stalled items, obligations coming due. This is the front of the
   document, on purpose — a handover that opens with a narrative of the last
   eight hours buries the thing the reader needs in the first thirty seconds.
2. **What did the last shift already do?** Every human decision with its
   reason, so the incoming controller does not redo work, reverse a call
   without knowing why it was made, or chase something already forwarded.

Printed on A4 because that is what a council prints on.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

from .models import utcnow

# Muted on paper — a printout that is 60% red is unreadable, and the point of
# the colour here is to let someone flick to the section they need.
INK = colors.HexColor("#1a1d23")
MUTED = colors.HexColor("#5b6472")
RULE = colors.HexColor("#c9d0da")
ACTION = colors.HexColor("#b3261e")
VERIFY = colors.HexColor("#8a5a00")
AWARE = colors.HexColor("#1b5e9e")
OBLIG = colors.HexColor("#a63b6e")
CRIT_BG = colors.HexColor("#fdf2f2")
HEAD_BG = colors.HexColor("#eef1f5")

PRIORITY_INK = {
    "action_required": ACTION,
    "verification_required": VERIFY,
    "situational_awareness": AWARE,
}


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontSize=19,
                                leading=23, textColor=INK, alignment=TA_LEFT,
                                spaceAfter=2),
        "sub": ParagraphStyle("s", parent=base["Normal"], fontSize=9.5,
                              leading=13, textColor=MUTED),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontSize=12.5,
                             leading=15, textColor=INK, spaceBefore=13,
                             spaceAfter=3),
        "h2crit": ParagraphStyle("h2c", parent=base["Heading2"], fontSize=12.5,
                                 leading=15, textColor=ACTION, spaceBefore=13,
                                 spaceAfter=3),
        "note": ParagraphStyle("n", parent=base["Normal"], fontSize=8.5,
                               leading=11, textColor=MUTED, spaceAfter=5),
        "body": ParagraphStyle("b", parent=base["Normal"], fontSize=9,
                               leading=12, textColor=INK),
        "cell": ParagraphStyle("c", parent=base["Normal"], fontSize=8,
                               leading=10, textColor=INK),
        "cellmuted": ParagraphStyle("cm", parent=base["Normal"], fontSize=7.5,
                                    leading=9.5, textColor=MUTED),
        "quote": ParagraphStyle("q", parent=base["Normal"], fontSize=9,
                                leading=12.5, textColor=INK, leftIndent=8,
                                borderPadding=6, backColor=HEAD_BG),
        "empty": ParagraphStyle("e", parent=base["Normal"], fontSize=8.5,
                                leading=11, textColor=MUTED,
                                fontName="Helvetica-Oblique"),
    }


def _esc(text) -> str:
    return (str(text or "").replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def _when(iso: str | None) -> str:
    """A timestamp in local time, which is the only time anyone in the room is
    thinking in. The audit trail is stored in UTC and the reportings arrive
    with their own offsets; printing either raw puts the paper an hour or
    thirteen out from the screen it was generated from."""
    if not iso:
        return "—"
    try:
        moment = datetime.fromisoformat(iso)
    except ValueError:
        return str(iso)[:16]
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone().strftime("%d %b %H:%M")


def _page_furniture(canvas, doc, shift_label: str) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 12 * mm, shift_label)
    canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, f"Page {doc.page}")
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.4)
    canvas.line(18 * mm, 15.5 * mm, A4[0] - 18 * mm, 15.5 * mm)
    # The disclaimer travels with the document, because a printout outlives the
    # screen it came from and will be read by people who never saw the app.
    canvas.setFont("Helvetica-Oblique", 6.5)
    canvas.drawString(18 * mm, 8 * mm,
                      "Impact Lab Wellington prototype — not an operational "
                      "emergency system. In an emergency, call 111.")
    canvas.restoreState()


# ---------------------------------------------------------------------------
# section builders
# ---------------------------------------------------------------------------


def _card_table(cards: list[dict], st: dict, *, extra=None,
                critical: bool = False) -> Table:
    rows = [[Paragraph("<b>Priority</b>", st["cellmuted"]),
             Paragraph("<b>What</b>", st["cellmuted"]),
             Paragraph("<b>Where</b>", st["cellmuted"]),
             Paragraph("<b>Age</b>", st["cellmuted"]),
             Paragraph("<b>Status</b>", st["cellmuted"])]]
    styles = [
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for card in cards:
        ink = PRIORITY_INK.get(card.get("priority"), MUTED)
        what = _esc(card.get("excerpt") or "(no text)")
        line = extra(card) if extra else None
        if line:
            what += f'<br/><font size="7" color="#5b6472">{_esc(line)}</font>'
        row = len(rows)
        rows.append([
            Paragraph(f'<font color="{ink.hexval()}"><b>'
                      f'{_esc(card.get("priority_label"))}</b></font>', st["cell"]),
            Paragraph(what, st["cell"]),
            Paragraph(_esc(card.get("location")), st["cell"]),
            Paragraph(_esc(card.get("age")), st["cellmuted"]),
            Paragraph(_esc(card.get("status")), st["cellmuted"]),
        ])
        if critical:
            styles.append(("BACKGROUND", (0, row), (-1, row), CRIT_BG))

    table = Table(rows, colWidths=[24 * mm, 76 * mm, 32 * mm, 18 * mm, 24 * mm],
                  repeatRows=1)
    table.setStyle(TableStyle(styles))
    return table


def _section(flow: list, st: dict, title: str, cards: list[dict], empty: str,
             *, sub: str | None = None, extra=None, critical: bool = False):
    style = st["h2crit"] if critical else st["h2"]
    flow.append(Paragraph(f"{_esc(title)} ({len(cards)})", style))
    if sub:
        flow.append(Paragraph(_esc(sub), st["note"]))
    if not cards:
        flow.append(Paragraph(_esc(empty), st["empty"]))
        return
    flow.append(_card_table(cards, st, extra=extra, critical=critical))


def _tiles(totals: dict, obligations: dict, st: dict) -> Table:
    cells = [
        ("Never opened", totals.get("never_acknowledged", 0), True),
        ("Open — action", totals.get("open_action_required", 0), False),
        ("Open — verification", totals.get("open_verification_required", 0), False),
        ("Obligations due", obligations.get("outstanding", 0), False),
        ("Overdue", obligations.get("overdue", 0), bool(obligations.get("overdue"))),
        ("Decisions this shift", totals.get("human_decisions_this_shift", 0), False),
    ]
    top = [Paragraph(f'<font size="15"><b>{n}</b></font>', st["cell"]) for _, n, _ in cells]
    bottom = [Paragraph(f'<font size="7">{_esc(label)}</font>', st["cellmuted"])
              for label, _, _ in cells]
    table = Table([top, bottom], colWidths=[29 * mm] * 6)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 6),
        ("BOX", (0, 0), (-1, -1), 0.4, RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, RULE),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]
    for i, (_, _, hot) in enumerate(cells):
        if hot:
            style.append(("TEXTCOLOR", (i, 0), (i, 0), ACTION))
            style.append(("BACKGROUND", (i, 0), (i, 1), CRIT_BG))
    table.setStyle(TableStyle(style))
    return table


def _decisions_table(decisions: list[dict], st: dict) -> Table:
    rows = [[Paragraph(f"<b>{h}</b>", st["cellmuted"])
             for h in ("Time", "Operator", "Did what", "Change", "Reason given")]]
    for d in decisions:
        change = ""
        if d.get("from") or d.get("to"):
            change = f'{d.get("from") or "—"} → {d.get("to") or "—"}'
        what = _esc((d.get("action") or "").replace("_", " "))
        if d.get("excerpt"):
            what += f'<br/><font size="6.5" color="#5b6472">{_esc(d["excerpt"])}</font>'
        rows.append([
            Paragraph(_when(d.get("at")), st["cellmuted"]),
            Paragraph(_esc(d.get("actor")), st["cellmuted"]),
            Paragraph(what, st["cell"]),
            Paragraph(_esc(change), st["cellmuted"]),
            Paragraph(_esc(d.get("note")), st["cell"]),
        ])
    table = Table(rows, colWidths=[20 * mm, 24 * mm, 46 * mm, 34 * mm, 50 * mm],
                  repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]))
    return table


def _obligations_table(rows_in: list[dict], st: dict) -> Table:
    rows = [[Paragraph(f"<b>{h}</b>", st["cellmuted"])
             for h in ("Due", "Countdown", "Obligation", "Owner", "Status")]]
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for o in rows_in:
        i = len(rows)
        label = _esc(o.get("label"))
        if o.get("score_bearing"):
            label += ' <font size="6.5" color="#b3261e">SCORED</font>'
        rows.append([
            Paragraph(_when(o.get("due_at")), st["cellmuted"]),
            Paragraph(f'<font color="{(ACTION if o.get("urgency") == "overdue" else OBLIG).hexval()}">'
                      f'<b>{_esc(o.get("countdown"))}</b></font>', st["cell"]),
            Paragraph(label, st["cell"]),
            Paragraph(_esc(o.get("owner_role")), st["cellmuted"]),
            Paragraph(_esc(o.get("urgency_label")), st["cellmuted"]),
        ])
        if o.get("urgency") in ("overdue", "due_now"):
            style.append(("BACKGROUND", (0, i), (-1, i), CRIT_BG))

    table = Table(rows, colWidths=[22 * mm, 24 * mm, 76 * mm, 28 * mm, 24 * mm],
                  repeatRows=1)
    table.setStyle(TableStyle(style))
    return table


# ---------------------------------------------------------------------------
# the document
# ---------------------------------------------------------------------------


def build(briefing: dict, obligation_rows: list[dict] | None = None) -> bytes:
    """Render a briefing to PDF bytes."""
    st = _styles()
    shift = briefing.get("shift", {})
    totals = briefing.get("totals", {})
    obligation_rows = obligation_rows or []
    ob_summary = {
        "outstanding": len(obligation_rows),
        "overdue": sum(1 for o in obligation_rows if o.get("urgency") == "overdue"),
    }

    operator = shift.get("operator") or "unknown"
    label = (f"Shift report · {operator} · "
             f"{_when(shift.get('started_at'))} – "
             f"{_when(shift.get('ended_at')) if shift.get('ended_at') else 'open'}")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=20 * mm,
        title=f"Shift report — {operator}",
        author="Wellington EOC reporting triage",
        subject="Shift handover briefing",
    )

    flow: list = []
    flow.append(Paragraph("Shift handover report", st["title"]))
    flow.append(Paragraph(
        f"<b>Outgoing:</b> {_esc(operator)} ({_esc(shift.get('role') or 'operator')}) &nbsp;·&nbsp; "
        f"<b>Shift:</b> {_when(shift.get('started_at'))} – "
        f"{_when(shift.get('ended_at')) if shift.get('ended_at') else 'still open'} &nbsp;·&nbsp; "
        f"<b>Generated:</b> {_when(briefing.get('generated_at') or utcnow().isoformat())}"
        f" &nbsp;·&nbsp; all times local",
        st["sub"]))
    flow.append(Spacer(1, 8))
    flow.append(_tiles(totals, ob_summary, st))
    flow.append(Spacer(1, 4))

    llm = briefing.get("llm_summary") or {}
    if llm.get("summary"):
        flow.append(Paragraph("Summary", st["h2"]))
        flow.append(Paragraph(_esc(llm["summary"]), st["quote"]))
        flow.append(Paragraph(
            "Drafted by a language model from the lists below. The lists are the "
            "record; this paragraph is a convenience and has not been checked.",
            st["note"]))

    # ---- part one: what to pick up ---------------------------------------
    flow.append(Paragraph("Part 1 — What to pick up first", st["h2"]))
    flow.append(Paragraph(
        "Ordered by how badly it needs you, not by when it arrived.", st["note"]))

    _section(flow, st, "Never opened — nobody has looked at these",
             briefing.get("never_acknowledged", []),
             "Everything open has been seen by someone.",
             sub="The reason this report exists. Start here.", critical=True)

    _section(flow, st, "Open and action required",
             briefing.get("open_action_required", []),
             "Nothing outstanding at action level.")

    _section(flow, st, "Stalled — opened, then no activity",
             briefing.get("stalled", []), "Nothing has gone quiet.",
             extra=lambda c: f"idle {c.get('idle_minutes')} min · last: "
                             f"{c.get('last_action')}"
                             + (f" — “{c['last_note']}”" if c.get("last_note") else ""))

    _section(flow, st, "Awaiting verification",
             briefing.get("awaiting_verification", []),
             "No open verification tasks.")

    _section(flow, st, "Forwarded — no reply yet",
             briefing.get("forwarded_awaiting_reply", []),
             "No outstanding forwards.",
             sub="We asked another agency and have not heard back.",
             extra=lambda c: f"{c.get('destination')} ({c.get('target')}) · "
                             f"waiting {c.get('waiting_minutes')} min"
                             + (" · dry run" if c.get("dry_run") else ""))

    if obligation_rows:
        flow.append(Paragraph(
            f"Administrative obligations outstanding ({len(obligation_rows)})", st["h2"]))
        flow.append(Paragraph(
            "From the uploaded timetable. Never ranked above an action-required "
            "reporting, but the scored ones count against the response.", st["note"]))
        flow.append(_obligations_table(obligation_rows, st))

    # ---- part two: what was already done ---------------------------------
    flow.append(PageBreak())
    flow.append(Paragraph("Part 2 — What the last shift did", st["h2"]))
    flow.append(Paragraph(
        "So you do not redo work, reverse a call without knowing why it was "
        "made, or chase something already handled.", st["note"]))

    _section(flow, st, "Ruled out — do not rework",
             briefing.get("ruled_out_this_shift", []),
             "Nothing was assessed as a false reporting this shift.",
             extra=lambda c: f"marked false by {c.get('marked_by')}"
                             + (f" — “{c['reason']}”" if c.get("reason") else ""))

    overrides = briefing.get("priority_overrides", [])
    flow.append(Paragraph(f"Priorities changed by hand ({len(overrides)})", st["h2"]))
    flow.append(Paragraph(
        "Where a human disagreed with the automated triage, and why.", st["note"]))
    if overrides:
        flow.append(_decisions_table(overrides, st))
    else:
        flow.append(Paragraph("No automated priorities were overridden.", st["empty"]))

    decisions = briefing.get("decisions", [])
    flow.append(Paragraph(f"Full decision log ({len(decisions)})", st["h2"]))
    flow.append(Paragraph(
        "Every operator action this shift, in order. This is the audit trail; "
        "the sections above are arrangements of it.", st["note"]))
    if decisions:
        flow.append(_decisions_table(decisions, st))
    else:
        flow.append(Paragraph("No operator decisions recorded.", st["empty"]))

    if shift.get("handover_note"):
        flow.append(KeepTogether([
            Paragraph("Note from the outgoing operator", st["h2"]),
            Paragraph(_esc(shift["handover_note"]), st["quote"]),
        ]))

    furniture = lambda canvas, d: _page_furniture(canvas, d, label)  # noqa: E731
    doc.build(flow, onFirstPage=furniture, onLaterPages=furniture)
    return buf.getvalue()


def filename(briefing: dict) -> str:
    shift = briefing.get("shift", {})
    operator = (shift.get("operator") or "shift").replace(" ", "-").replace("/", "-")
    stamp = utcnow().astimezone().strftime("%Y%m%d-%H%M")
    return f"shift-report-{operator}-{stamp}.pdf"
