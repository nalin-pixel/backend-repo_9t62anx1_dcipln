"""
Database Schemas for the Barber Booking app

Each Pydantic model represents a collection in MongoDB.
Collection name is the lowercase of the class name.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class Barber(BaseModel):
    name: str = Field(..., description="Barber full name")
    avatar_url: Optional[str] = Field(None, description="Optional avatar image URL")
    bio: Optional[str] = Field(None, description="Short bio or specialties")

class Service(BaseModel):
    name: str = Field(..., description="Service name, e.g., Haircut")
    description: Optional[str] = Field(None, description="Service details")
    duration_min: int = Field(..., ge=5, le=240, description="Duration in minutes")
    price: float = Field(..., ge=0, description="Price in dollars")

class Appointment(BaseModel):
    customer_name: str = Field(..., description="Customer full name")
    customer_phone: str = Field(..., description="Contact phone")
    barber_id: str = Field(..., description="ID of the barber (stringified ObjectId)")
    service_name: str = Field(..., description="Service name selected")
    start_time: datetime = Field(..., description="Appointment start time (UTC or local ISO)")
    end_time: datetime = Field(..., description="Computed end time")
    duration_min: int = Field(..., ge=5, le=240, description="Duration in minutes")
    notes: Optional[str] = Field(None, description="Optional notes")
    status: str = Field("booked", description="Appointment status: booked|canceled|completed")
