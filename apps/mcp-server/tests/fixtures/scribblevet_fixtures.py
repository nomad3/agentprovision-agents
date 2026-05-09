"""Mock-ScribbleVet fixtures for the scribblevet adapter tests.

Snapshotted against the SOAP shape ScribbleVet's Browser Companion
writes today (per the 2026-05-09 research doc) plus the OAuth
client_credentials response shape that Instinct Science's Partner API
is expected to use post-acquisition. Each fixture is the raw JSON we
expect the upstream API to return so the adapter's normalization
helpers can be exercised without hitting the network.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# OAuth token exchange (Bearer flow — same shape as Covetrus Pulse)
# ---------------------------------------------------------------------------

OAUTH_TOKEN_RESPONSE = {
    "access_token": "fake-scribblevet-token-xyz789",
    "token_type": "Bearer",
    "expires_in": 3600,
    "scope": "notes.read notes.search",
}


# ---------------------------------------------------------------------------
# List endpoint — recent notes (15-min window)
# ---------------------------------------------------------------------------

NOTES_LIST = {
    "results": [
        {
            "id": "sv_note_1001",
            "visit_date": "2026-05-09T09:15:00-07:00",
            "finalized_at": "2026-05-09T09:48:00-07:00",
            "dvm_id": "dvm_castillo",
            "dvm_name": "Dr. Angelo Castillo",
            "patient_id": "pat_8472",
            "patient_name": "Mochi",
            "client_id": "client_2210",
            "client_name": "Maria Lopez",
            "species": "feline",
            "summary": "T4 recheck — methimazole working, energy improved",
            "status": "finalized",
        },
        {
            "id": "sv_note_1002",
            "visit_date": "2026-05-09T10:30:00-07:00",
            "finalized_at": "2026-05-09T11:05:00-07:00",
            "dvm_id": "dvm_castillo",
            "dvm_name": "Dr. Angelo Castillo",
            "patient_id": "pat_8500",
            "patient_name": "Bailey",
            "client_id": "client_2230",
            "client_name": "James Kim",
            "species": "canine",
            "summary": "Annual wellness — clean physical exam",
            "status": "finalized",
        },
        {
            # Bad row — no note_id. Adapter must drop this so the ingest
            # workflow doesn't ever see an empty-key observation.
            "visit_date": "2026-05-09T11:00:00-07:00",
            "patient_name": "ghost",
        },
    ],
}


# ---------------------------------------------------------------------------
# Get-note endpoint — full SOAP body (single-pet visit)
# ---------------------------------------------------------------------------

NOTE_FULL = {
    "id": "sv_note_1001",
    "visit_date": "2026-05-09T09:15:00-07:00",
    "finalized_at": "2026-05-09T09:48:00-07:00",
    "dvm_id": "dvm_castillo",
    "dvm_name": "Dr. Angelo Castillo",
    "location_id": "anaheim",
    "patient_id": "pat_8472",
    "patient_name": "Mochi",
    "species": "feline",
    "breed": "Domestic Shorthair",
    "sex": "MN",
    "date_of_birth": "2019-03-14",
    "weight": {"value_kg": 5.2, "measured_at": "2026-05-09"},
    "client_id": "client_2210",
    "client_name": "Maria Lopez",
    "client_phone": "+17145551234",
    "soap": {
        "subjective": (
            "6yo MN DSH, hyperthyroid since April 2026 on methimazole "
            "2.5mg PO BID. Owner reports increased energy and steady "
            "appetite over the past 2 weeks. No vomiting, no PU/PD."
        ),
        "objective": (
            "T 101.4F, HR 200, RR 32, BCS 5/9, WT 5.2kg (up from 5.1kg). "
            "Murmur grade I/VI LAA. Normal abdominal palpation. Coat "
            "improved over April visit."
        ),
        "assessment": (
            "Hyperthyroidism — well controlled on current dose. T4 still "
            "pending; will adjust dose only if T4 below normal range."
        ),
        "plan": (
            "Continue methimazole 2.5mg PO BID. T4 panel today, results "
            "tomorrow. Recheck in 90 days. Owner to call if any vomiting "
            "or appetite drop."
        ),
    },
    "client_instructions": (
        "Continue Mochi's methimazole twice daily with food. We'll call "
        "tomorrow with the T4 results — call us at the office if she "
        "stops eating or starts vomiting."
    ),
    "diagnoses": [
        {"name": "Hyperthyroidism", "icd_like_code": "E05.9", "status": "stable"},
    ],
    "medications": [
        {"name": "Methimazole", "dose": "2.5mg PO BID", "duration_days": 90},
    ],
    "vaccines_administered": [],
    "additional_pets": [],
    "status": "finalized",
}


# ---------------------------------------------------------------------------
# Get-note endpoint — multi-pet visit (a single ScribbleVet note covers two pets)
# ---------------------------------------------------------------------------

NOTE_MULTI_PET = {
    "id": "sv_note_2002",
    "visit_date": "2026-05-09T13:00:00-07:00",
    "finalized_at": "2026-05-09T13:35:00-07:00",
    "dvm_id": "dvm_patel",
    "dvm_name": "Dr. Patel",
    "location_id": "mission_viejo",
    "patient_id": "pat_9101",
    "patient_name": "Cookie",
    "species": "canine",
    "breed": "Beagle",
    "sex": "FS",
    "date_of_birth": "2020-06-01",
    "weight": {"value_kg": 12.3, "measured_at": "2026-05-09"},
    "client_id": "client_3100",
    "client_name": "Aiko Tanaka",
    "client_phone": "+19495557788",
    "soap": {
        "subjective": "Both dogs in for annual wellness; owner reports both eating well.",
        "objective": "Cookie: BCS 5/9, no abnormalities. (See additional_pets for Cream.)",
        "assessment": "Cookie: healthy.",
        "plan": "DAPP + Bordetella + Lepto today. Recheck in 1 year.",
    },
    "client_instructions": (
        "Both dogs are due back in 1 year for their annual wellness. "
        "Stool check kits sent home for each."
    ),
    "diagnoses": [],
    "medications": [],
    "vaccines_administered": [
        {"name": "DAPP", "lot": "L552-A", "given_at": "2026-05-09"},
        {"name": "Bordetella", "lot": "B221-C", "given_at": "2026-05-09"},
        {"name": "Lepto", "lot": "P109-D", "given_at": "2026-05-09"},
    ],
    "additional_pets": [
        {
            "patient_id": "pat_9102",
            "patient_name": "Cream",
            "species": "canine",
            "breed": "Beagle",
            "soap": {
                "subjective": "Sister to Cookie, same household.",
                "objective": "BCS 5/9, mild dental tartar.",
                "assessment": "Healthy; pre-dental.",
                "plan": "Recommend dental cleaning Q1 2027. DAPP + Bordetella + Lepto today.",
            },
        },
    ],
    "status": "finalized",
}


# ---------------------------------------------------------------------------
# Search endpoint — text-search across notes
# ---------------------------------------------------------------------------

NOTES_SEARCH = {
    "matches": [
        {
            "id": "sv_note_0801",
            "visit_date": "2026-03-12T10:00:00-07:00",
            "patient_id": "pat_5500",
            "patient_name": "Bella",
            "client_name": "Sara Patel",
            "summary": "Left hind limp — orthopedic eval; OFA-style hip image planned.",
        },
        {
            "id": "sv_note_0901",
            "visit_date": "2026-04-04T11:30:00-07:00",
            "patient_id": "pat_5500",
            "patient_name": "Bella",
            "client_name": "Sara Patel",
            "summary": "Limp recheck — improved on rest + carprofen; continue 2 more weeks.",
        },
    ],
}


# Bare-list shape (some endpoints skip the {results: ...} envelope)
NOTES_LIST_BARE = NOTES_LIST["results"]
