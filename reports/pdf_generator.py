from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

def generate_fir_pdf(response, complaint):
    p = canvas.Canvas(response, pagesize=A4)

    p.setTitle(f"FIR-{complaint.tracking_id}")
    y = 800
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, y, "Crime Reporting & Investigation Management System")
    y -= 40
    p.setFont("Helvetica", 12)
    p.drawString(50, y, f"Tracking ID: {complaint.tracking_id}")
    y -= 25
    p.drawString(50, y, f"Title: {complaint.title}")

    y -=25
    p.drawString(50, y, f"Category: {complaint.category}")

    y -=25
    p.drawString(20, y, f"Priority: {complaint.priority}")

    y -=25
    p.drawString(50, y, f"Status: {complaint.status}")

    y -=25 
    p.drawString(50, y, f"Citizen: {complaint.citizen}")

    y -= 25
    p.drawString(50, y, f"Date: {complaint.created_at.strftime('%d-%m-%Y')}")

    y -=40
    p.drawString(50, y, "Description")

    y -=25
    text = p.beginText(50, y)
    for line in complaint.description.split('\n'):
        text.textLine(line)

    if hasattr(complaint, 'investigation'):
        officer = (
            complaint.investigation.assigned_officer
        )

        p.drawString(50, y, f"Assigned Officer: {officer}")
        y -= 25

    evidence_count = complaint.evidence.count()
    p.drawString(50, y, f"Evidence Files: {evidence_count}")

    p.setFont("Helvetica-Bold", 18)
    p.drawString(50, 820, "FIRST INFORMATION REPORT (FIR)")

    p.drawText(text)
    p.showPage()
    p.save()