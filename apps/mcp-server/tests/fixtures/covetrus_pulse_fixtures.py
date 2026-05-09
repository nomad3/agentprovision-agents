"""Mock-Pulse fixtures for the covetrus_pulse adapter tests.

Snapshotted from the Otto / SmartFlow / Chckvet partner-published payload
shapes (the closest behavioral analogs we have until partner intake confirms
the real Pulse Connect schema). Each fixture is the raw JSON we expect the
upstream API to return so the adapter's normalization helpers can be
exercised without hitting the network.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# OAuth token exchange
# ---------------------------------------------------------------------------

OAUTH_TOKEN_RESPONSE = {
    "access_token": "fake-access-token-abc123",
    "token_type": "Bearer",
    "expires_in": 3600,
    "scope": "patient.read appointment.read invoice.read",
}


# ---------------------------------------------------------------------------
# Patient (full chart)
# ---------------------------------------------------------------------------

PATIENT_FULL = {
    "id": "pat_8472",
    "name": "Mochi",
    "species": "feline",
    "breed": "Domestic Shorthair",
    "sex": "MN",
    "date_of_birth": "2019-03-14",
    "weight_history": [
        {"date": "2025-11-18", "weight_kg": 4.8},
        {"date": "2026-04-22", "weight_kg": 5.1},
    ],
    "vaccines": [
        {"name": "FVRCP", "date": "2025-11-18", "next_due": "2026-11-18"},
        {"name": "Rabies", "date": "2024-08-12", "next_due": "2027-08-12"},
    ],
    "current_medications": [
        {"name": "Methimazole", "dose": "2.5mg PO BID", "started": "2026-04-22"},
    ],
    "allergies": ["chicken", "amoxicillin"],
    "diagnoses": [
        {"name": "Hyperthyroidism", "diagnosed": "2026-04-22"},
    ],
    "last_visit": {
        "date": "2026-04-22",
        "doctor": "Dr. Castillo",
        "reason": "T4 recheck — hyperthyroidism management",
        "location_id": "anaheim",
    },
    "owner": {
        "id": "client_2210",
        "name": "Maria Lopez",
        "phone": "+17145551234",
        "email": "maria@example.com",
    },
    "location_id": "anaheim",
}


PATIENT_DIFFERENT_LOCATION = {
    **PATIENT_FULL,
    "id": "pat_9999",
    "location_id": "mission_viejo",
}


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------

APPOINTMENTS_LIST = {
    "results": [
        {
            "id": "appt_1001",
            "scheduled_at": "2026-05-09T10:00:00-07:00",
            "duration_minutes": 30,
            "status": "completed",
            "reason": "annual_wellness",
            "patient_id": "pat_8472",
            "patient_name": "Mochi",
            "client_name": "Maria Lopez",
            "doctor": "Dr. Castillo",
            "location_id": "anaheim",
        },
        {
            "id": "appt_1002",
            "scheduled_at": "2026-05-09T11:30:00-07:00",
            "duration_minutes": 45,
            "status": "completed",
            "reason": "dental",
            "patient_id": "pat_8500",
            "patient_name": "Bailey",
            "client_name": "James Kim",
            "doctor": "Dr. Castillo",
            "location_id": "buena_park",
        },
        {
            "id": "appt_1003",
            "scheduled_at": "2026-05-09T14:00:00-07:00",
            "duration_minutes": 60,
            "status": "scheduled",
            "reason": "surgery_consult",
            "patient_id": "pat_8650",
            "patient_name": "Luna",
            "client_name": "Aiko Tanaka",
            "doctor": "Dr. Patel",
            "location_id": "mission_viejo",
        },
    ],
}


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

INVOICES_LIST = {
    "results": [
        {
            "id": "inv_5001",
            "date": "2026-05-08",
            "patient_id": "pat_8472",
            "patient_name": "Mochi",
            "client_name": "Maria Lopez",
            "location_id": "anaheim",
            "amount": 482.50,
            "service_type": "wellness",
            "line_items": [
                {"sku": "EXAM_WELL", "description": "Wellness exam", "amount": 75.00},
                {"sku": "VAC_FVRCP", "description": "FVRCP booster", "amount": 32.50},
                {"sku": "LAB_T4", "description": "T4 panel", "amount": 175.00},
                {"sku": "RX_METH", "description": "Methimazole 30ct", "amount": 200.00},
            ],
            "payment_status": "paid",
        },
        {
            "id": "inv_5002",
            "date": "2026-05-08",
            "patient_id": "pat_8500",
            "patient_name": "Bailey",
            "client_name": "James Kim",
            "location_id": "buena_park",
            "amount": 925.00,
            "service_type": "dental",
            "line_items": [
                {"sku": "DENT_FULL", "description": "Full dental w/ extractions", "amount": 850.00},
                {"sku": "ANES", "description": "Anesthesia", "amount": 75.00},
            ],
            "payment_status": "paid",
        },
        {
            "id": "inv_5003",
            "date": "2026-05-08",
            "patient_id": "pat_8650",
            "patient_name": "Luna",
            "client_name": "Aiko Tanaka",
            "location_id": "mission_viejo",
            "amount": 1620.00,
            "service_type": "surgery",
            "line_items": [
                {"sku": "SURG_TPLO", "description": "TPLO repair", "amount": 1500.00},
                {"sku": "RX_PAIN", "description": "Post-op pain meds", "amount": 120.00},
            ],
            "payment_status": "pending",
        },
        {
            "id": "inv_5004",
            "date": "2026-05-08",
            "patient_id": "pat_8472",
            "patient_name": "Mochi",
            "client_name": "Maria Lopez",
            "location_id": "anaheim",
            "amount": 215.00,
            "service_type": "wellness",
            "line_items": [
                {"sku": "VAC_RAB", "description": "Rabies booster", "amount": 35.00},
                {"sku": "FECAL", "description": "Fecal exam", "amount": 45.00},
                {"sku": "EXAM_REC", "description": "Recheck exam", "amount": 135.00},
            ],
            "payment_status": "paid",
        },
    ],
}


# ---------------------------------------------------------------------------
# Bare-list shape (some Pulse endpoints skip the {results: ...} envelope)
# ---------------------------------------------------------------------------

INVOICES_BARE_LIST = INVOICES_LIST["results"]
