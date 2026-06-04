"""Tests for the deterministic echo extractor (Central Vet OS, task #22).

The fixtures are the REAL measurement-block + signalment text from the on-disk
Winnie Nieto machine export / report (health-pets/docs/data/, inspected
2026-06-04) — so the parser is validated against authentic vendor layout
without depending on the external PDF in CI.
"""

from __future__ import annotations

from app.services.vet import echo_extractor as ee

# Real "Adult Echo: Measurements and Calculations" block (multi-column text,
# up to three `label value unit` triples per line; modality parens carry digits).
WINNIE_MEASUREMENTS = """\
Adult Echo: Measurements and Calculations
LVIDd (2D) 2.06 cm LVAd (A4C) 4.28 cm² EF (A4C) 69.3 %
LVPWd (2D) 0.508 cm LVAs (A4C) 2.09 cm² LV Mass-c 18.4 g
EDV (A4C) 5.53 ml IVSd (2D) 0.545 cm
ESV (A4C) 1.70 ml LA Area 3.66 cm²
IVS/LVPW (2D) 1.07 LA/Ao (2D) 1.49
IVSd (MM) 0.555 cm LVPW % (MM) 65.0 %
LVIDd (MM) 2.00 cm FS (MM-Teich)35.5 % LA Dimen 1.6 cm
LVPWd (MM) 0.412 cm EF (MM-Teich)68.0 % AoR Diam 1.1 cm
IVSs (MM) 0.805 cm LA/Ao (MM) 1.45
LVIDs (MM) 1.29 cm MV D-E Slope 21.2 cm/s
MR Vmax 514 cm/s
"""

# Real finalised-report signalment narrative.
WINNIE_REPORT = """\
Cardiac Evaluation Report
Winnie Nieto
History
Signalment
13y FS Chihuahua
Presenting Complaint: Historical murmur
Physical Exam: Wt: 4.0kg, BAR-H, MM: pink and moist, HR: 92, Grade II/VI murmur
"""


def _extract():
    return ee.build_extraction(
        measurement_text=WINNIE_MEASUREMENTS, report_text=WINNIE_REPORT
    )


def test_modality_paren_digits_not_read_as_value():
    """The '(2D)' / '(MM-Teich)' modality digits must NOT be mistaken for the
    value — LVIDd(2D) is 2.06, not 2."""
    x = _extract()
    lvidd = x.by_field["lvidd"]
    assert lvidd.value == 2.06          # from (2D), NOT the "2" in "(2D)"
    assert lvidd.unit == "cm"
    assert lvidd.modality == "2D"


def test_key_fields_extracted_with_values():
    x = _extract()
    assert x.by_field["lvids"].value == 1.29
    assert x.by_field["la_ao"].value == 1.49      # 2D preferred over MM (1.45)
    assert x.by_field["fs"].value == 35.5
    assert x.by_field["ef"].value == 69.3         # A4C, first seen, tie kept
    assert x.by_field["ivsd"].value == 0.545
    assert x.by_field["mr_vmax"].value == 514


def test_ratio_field_high_confidence_without_unit():
    x = _extract()
    la_ao = x.by_field["la_ao"]
    assert la_ao.unit == ""
    assert la_ao.confidence == ee.HIGH            # ratio: no unit penalty


def test_2d_preferred_over_mm_on_tie():
    x = _extract()
    # Both LVIDd(2D)=2.06 and LVIDd(MM)=2.00 are HIGH; 2D wins.
    assert x.by_field["lvidd"].modality == "2D"


def test_signalment_parsed():
    x = _extract()
    sig = x.signalment
    assert sig["age_years"] == 13
    assert sig["sex"] == "FS"
    assert sig["breed"] == "Chihuahua"
    assert sig["weight_kg"] == 4.0
    assert sig["species"] == "canine"


def test_species_canine_not_misread_feline_from_cat_substring():
    """Regression: a bare 'cat' SUBSTRING inside words like 'indicate' must NOT
    mislabel a dog as feline (real-PDF bug, 2026-06-04)."""
    report = "13y FS Chihuahua. Findings indicate a location-specific murmur."
    x = ee.build_extraction(measurement_text=WINNIE_MEASUREMENTS, report_text=report)
    assert x.signalment["species"] == "canine"


def test_species_feline_on_word_boundary():
    report = "8y MN Domestic Shorthair cat with a murmur."
    x = ee.build_extraction(measurement_text=WINNIE_MEASUREMENTS, report_text=report)
    assert x.signalment["species"] == "feline"


def test_winnie_is_complete_and_no_review():
    """Winnie is a clean Stage-B1 case: complete + all in range → no review."""
    x = _extract()
    assert x.completeness.complete is True
    assert x.completeness.missing == []
    assert x.needs_review is False
    assert x.review_reasons == []


def test_la_ao_outlier_triggers_review():
    text = WINNIE_MEASUREMENTS.replace("LA/Ao (2D) 1.49", "LA/Ao (2D) 2.10")
    x = ee.build_extraction(measurement_text=text, report_text=WINNIE_REPORT)
    assert x.by_field["la_ao"].outlier_flag is True
    assert "LA:Ao" in (x.by_field["la_ao"].outlier_reason or "")
    assert x.needs_review is True


def test_la_ao_boundary_1_6_triggers_review():
    """ACVIM Stage-B2 threshold is LA:Ao ≥1.6 — exactly 1.60 must escalate
    (Luna clinical review: >= not >)."""
    text = WINNIE_MEASUREMENTS.replace("LA/Ao (2D) 1.49", "LA/Ao (2D) 1.60")
    x = ee.build_extraction(measurement_text=text, report_text=WINNIE_REPORT)
    assert x.by_field["la_ao"].outlier_flag is True
    assert "B2" in (x.by_field["la_ao"].outlier_reason or "")
    assert x.needs_review is True


def test_lviddn_computed_for_winnie():
    """LVIDdN = LVIDd(cm)/weight^0.294 = 2.06/4.0^0.294 ≈ 1.37 → below B2 (1.7)."""
    x = _extract()
    lviddn = x.by_field["lviddn"]
    assert abs(lviddn.value - 1.37) < 0.02
    assert lviddn.outlier_flag is False


def test_lviddn_b2_threshold_triggers_review():
    text = WINNIE_MEASUREMENTS.replace("LVIDd (2D) 2.06 cm", "LVIDd (2D) 2.60 cm")
    x = ee.build_extraction(measurement_text=text, report_text=WINNIE_REPORT)
    # 2.60/4.0^0.294 ≈ 1.73 ≥ 1.7
    assert x.by_field["lviddn"].value >= 1.7
    assert x.by_field["lviddn"].outlier_flag is True
    assert x.needs_review is True


def test_unknown_breed_leaves_species_unset():
    """An unknown breed with no explicit dog/cat signal must NOT default canine
    — species stays missing so a human confirms it (Luna clinical review)."""
    report = "3y MN Keeshond, presented for a murmur."
    x = ee.build_extraction(measurement_text=WINNIE_MEASUREMENTS, report_text=report)
    assert "species" not in x.signalment
    assert "species" in x.completeness.missing
    assert x.needs_review is True


def test_fs_outlier_triggers_review():
    text = WINNIE_MEASUREMENTS.replace("FS (MM-Teich)35.5 %", "FS (MM-Teich)18.0 %")
    x = ee.build_extraction(measurement_text=text, report_text=WINNIE_REPORT)
    assert x.by_field["fs"].outlier_flag is True
    assert x.needs_review is True


def test_missing_la_ao_fails_completeness():
    text = WINNIE_MEASUREMENTS.replace("LA/Ao (2D) 1.49", "").replace("LA/Ao (MM) 1.45", "")
    x = ee.build_extraction(measurement_text=text, report_text=WINNIE_REPORT)
    assert x.completeness.complete is False
    assert "LA:Ao" in x.completeness.missing
    assert x.needs_review is True


def test_missing_signalment_fails_completeness():
    x = ee.build_extraction(measurement_text=WINNIE_MEASUREMENTS, report_text="")
    assert x.completeness.complete is False
    # species + weight come from the report narrative, absent here.
    assert "weight" in x.completeness.missing


def test_systolic_function_satisfied_by_fs_when_lvids_absent():
    text = WINNIE_MEASUREMENTS.replace("LVIDs (MM) 1.29 cm", "")
    x = ee.build_extraction(measurement_text=text, report_text=WINNIE_REPORT)
    # LVIDs gone but FS present → systolic-function requirement still met.
    assert "LVIDs/FS/EF (systolic function)" not in x.completeness.missing
    assert x.completeness.complete is True
