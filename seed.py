"""Seed demo data: python seed.py"""
from decimal import Decimal

from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.models import Centre, CentreTest, DiagnosticTest

Base.metadata.create_all(engine)
TESTS = ["Complete Blood Count", "Lipid Profile", "HbA1c", "Thyroid Panel", "Chest X-Ray"]
CENTRES = {
    ("EVE Diagnostics Saket", "New Delhi"): {"Complete Blood Count": "350", "Lipid Profile": "600", "HbA1c": "450"},
    ("EVE Diagnostics Indiranagar", "Bengaluru"): {"Complete Blood Count": "300", "Thyroid Panel": "700", "Chest X-Ray": "550"},
}
with SessionLocal() as db:
    tests = {}
    for n in TESTS:
        t = db.scalar(select(DiagnosticTest).where(DiagnosticTest.name == n)) or DiagnosticTest(name=n)
        db.add(t); db.flush(); tests[n] = t
    for (name, loc), offer in CENTRES.items():
        c = db.scalar(select(Centre).where(Centre.name == name, Centre.location == loc))
        if not c:
            c = Centre(name=name, location=loc); db.add(c); db.flush()
            for tn, price in offer.items():
                db.add(CentreTest(centre_id=c.id, test_id=tests[tn].id, price=Decimal(price)))
    db.commit()
print("seeded")
