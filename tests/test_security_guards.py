import pytest
from app import sanitize_filename, verify_file_signature
from prc_physics import calculate_pore_compressibility, calculate_washburn_radius

def test_filename_sanitization_path_traversal():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("..\\..\\Windows\\System32.exe") == "System32.exe"
    assert sanitize_filename("safe_report.xlsx") == "safe_report.xlsx"
    assert sanitize_filename("../../../../app.py") == "app.py"
    assert sanitize_filename("") == "unnamed_file"

def test_verify_file_signature_xlsx():
    # Valid ZIP header
    xlsx_bytes = b"PK\x03\x04somezipcontent"
    assert verify_file_signature(xlsx_bytes, "test.xlsx") is True
    # Spoofed exe renamed to xlsx
    exe_bytes = b"MZsomeexecontent"
    assert verify_file_signature(exe_bytes, "test.xlsx") is False

def test_verify_file_signature_xls():
    # Valid OLE header
    xls_bytes = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1somexlscontent"
    assert verify_file_signature(xls_bytes, "test.xls") is True
    # Spoofed renamed file
    xlsx_bytes = b"PK\x03\x04somezipcontent"
    assert verify_file_signature(xlsx_bytes, "test.xls") is False

def test_verify_file_signature_pdf():
    pdf_bytes = b"%PDF-1.4\ncontent"
    assert verify_file_signature(pdf_bytes, "test.pdf") is True
    assert verify_file_signature(b"PK\x03\x04", "test.pdf") is False

def test_verify_file_signature_csv_and_text():
    csv_bytes = b"pressure,saturation,water\n10,0.5,0.2"
    assert verify_file_signature(csv_bytes, "test.csv") is True
    
    # Binary in text file
    exe_bytes = b"MZsomeexe"
    assert verify_file_signature(exe_bytes, "test.csv") is False
    
    null_bytes = b"pressure\x00saturation"
    assert verify_file_signature(null_bytes, "test.csv") is False

def test_physics_plausibility_guards_compressibility():
    # Valid
    assert calculate_pore_compressibility(25.0, 24.0, 100.0) > 0
    # Invalid initial porosity
    with pytest.raises(ValueError, match="Initial porosity must be strictly greater than zero and less than or equal to 100"):
        calculate_pore_compressibility(-5.0, 24.0, 100.0)
    with pytest.raises(ValueError, match="Initial porosity must be strictly greater than zero and less than or equal to 100"):
        calculate_pore_compressibility(120.0, 24.0, 100.0)
    # Invalid final porosity
    with pytest.raises(ValueError, match="Final porosity under elevated pressure cannot exceed initial porosity"):
        calculate_pore_compressibility(25.0, 26.0, 100.0)

def test_physics_plausibility_guards_washburn():
    # Valid
    assert calculate_washburn_radius(100.0, 140.0, 480.0) > 0
    # Invalid contact angle
    with pytest.raises(ValueError, match="Contact angle must be between 0 and 180 degrees"):
        calculate_washburn_radius(100.0, -10.0, 480.0)
    with pytest.raises(ValueError, match="Contact angle must be between 0 and 180 degrees"):
        calculate_washburn_radius(100.0, 190.0, 480.0)
    # Invalid interfacial tension
    with pytest.raises(ValueError, match="Interfacial tension must be strictly greater than zero"):
        calculate_washburn_radius(100.0, 140.0, -10.0)
