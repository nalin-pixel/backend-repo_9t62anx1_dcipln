import os
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import db, create_document, get_documents

app = FastAPI(title="Barber Booking API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Public health/info endpoints
@app.get("/")
def read_root():
    return {"message": "Barber Booking API running"}

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = getattr(db, 'name', "✅ Connected")
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response


# Schemas for request bodies
class BarberIn(BaseModel):
    name: str
    avatar_url: Optional[str] = None
    bio: Optional[str] = None

class ServiceIn(BaseModel):
    name: str
    description: Optional[str] = None
    duration_min: int
    price: float

class AppointmentIn(BaseModel):
    customer_name: str
    customer_phone: str
    barber_id: str
    service_name: str
    start_time: datetime
    duration_min: int
    notes: Optional[str] = None

class AppointmentOut(BaseModel):
    id: str
    customer_name: str
    customer_phone: str
    barber_id: str
    service_name: str
    start_time: datetime
    end_time: datetime
    duration_min: int
    notes: Optional[str] = None
    status: str


# Helper to convert Mongo _id to string
from bson import ObjectId

def serialize(doc):
    if not doc:
        return doc
    doc = dict(doc)
    if doc.get("_id"):
        doc["id"] = str(doc.pop("_id"))
    return doc

# Privacy helpers

def mask_name(name: str) -> str:
    try:
        parts = [p for p in name.strip().split(" ") if p]
        if not parts:
            return "Customer"
        masked_parts = []
        for p in parts:
            if len(p) <= 2:
                masked_parts.append(p[0] + "*")
            else:
                masked_parts.append(p[0] + "***")
        return " ".join(masked_parts)
    except Exception:
        return "Customer"


def mask_phone(phone: str) -> str:
    digits = [c for c in phone if c.isdigit()]
    if len(digits) < 4:
        return "***"
    last4 = "".join(digits[-4:])
    return f"***-***-{last4}"


# Seed default barbers and services if empty
@app.on_event("startup")
async def seed_defaults():
    for name in ["John Fade", "Lisa Shear", "Mike Lineup"]:
        if db["barber"].count_documents({"name": name}) == 0:
            create_document("barber", {"name": name, "bio": "Pro barber"})

    # Update default services and ensure Haircut price is 18
    default_services = [
        {"name": "Haircut", "duration_min": 30, "price": 18.0},
        {"name": "Beard Trim", "duration_min": 15, "price": 15.0},
        {"name": "Haircut + Beard", "duration_min": 45, "price": 35.0},
    ]
    for s in default_services:
        existing = db["service"].find_one({"name": s["name"]})
        if not existing:
            create_document("service", s)
        else:
            # Ensure "Haircut" price reflects the new value and keep duration consistent
            if s["name"] == "Haircut":
                db["service"].update_one({"_id": existing["_id"]}, {"$set": {"price": 18.0, "duration_min": s["duration_min"]}})


# Catalog endpoints
@app.get("/api/barbers")
def list_barbers():
    items = get_documents("barber")
    return [serialize(i) for i in items]

@app.post("/api/barbers")
def add_barber(body: BarberIn):
    _id = create_document("barber", body)
    doc = db["barber"].find_one({"_id": ObjectId(_id)})
    return serialize(doc)

@app.get("/api/services")
def list_services():
    items = get_documents("service")
    return [serialize(i) for i in items]

@app.post("/api/services")
def add_service(body: ServiceIn):
    _id = create_document("service", body)
    doc = db["service"].find_one({"_id": ObjectId(_id)})
    return serialize(doc)


# Appointment endpoints
@app.get("/api/appointments")
def list_appointments(barber_id: Optional[str] = None):
    q = {"barber_id": barber_id} if barber_id else {}
    items = get_documents("appointment", q)
    # Apply privacy masking on public listing
    sanitized = []
    for i in items:
        i = serialize(i)
        i["customer_name"] = mask_name(i.get("customer_name", ""))
        i["customer_phone"] = mask_phone(i.get("customer_phone", ""))
        # Avoid leaking notes in the listing
        if "notes" in i:
            i["notes"] = None
        sanitized.append(i)
    return sanitized

@app.get("/api/appointments/check")
def check_availability(
    barber_id: str = Query(..., description="Barber ID"),
    start_time: datetime = Query(..., description="ISO start time"),
    duration_min: int = Query(..., description="Duration in minutes"),
):
    start = start_time
    end = start + timedelta(minutes=duration_min)
    conflict = db["appointment"].find_one({
        "barber_id": barber_id,
        "status": {"$ne": "canceled"},
        "$or": [
            {"start_time": {"$lt": end}, "end_time": {"$gt": start}}
        ]
    })
    return {"available": conflict is None}

@app.post("/api/appointments")
def create_appointment(body: AppointmentIn):
    # compute end_time and check overlap
    start = body.start_time
    end = start + timedelta(minutes=body.duration_min)

    conflict = db["appointment"].find_one({
        "barber_id": body.barber_id,
        "status": {"$ne": "canceled"},
        "$or": [
            {"start_time": {"$lt": end}, "end_time": {"$gt": start}}
        ]
    })
    if conflict:
        raise HTTPException(status_code=400, detail="Time slot not available")

    data = body.model_dump()
    data["end_time"] = end
    data["status"] = "booked"
    _id = create_document("appointment", data)
    doc = db["appointment"].find_one({"_id": ObjectId(_id)})
    return serialize(doc)

@app.patch("/api/appointments/{appointment_id}/cancel")
def cancel_appointment(appointment_id: str):
    oid = ObjectId(appointment_id)
    res = db["appointment"].update_one({"_id": oid}, {"$set": {"status": "canceled", "updated_at": datetime.utcnow()}})
    if res.modified_count == 0:
        raise HTTPException(status_code=404, detail="Appointment not found")
    doc = db["appointment"].find_one({"_id": oid})
    return serialize(doc)
