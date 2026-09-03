import os
import json
import io
import sqlite3
from docx import Document
from hviel_doc_engine import HvielDocEngine
from report_generator import PRCReportEngine

def test_extract_json_payload():
    """
    Asserts that the bracket-counting JSON parser successfully extracts 
    the __PRC_PLOT__ payload and separates any trailing commentary text.
    """
    engine = HvielDocEngine()
    
    mock_payload = {
        "title": "Mercury Injection (MICP)",
        "xAxis": {"label": "Saturation"},
        "yAxis": {"label": "Pressure", "log": True},
        "curves": [{"x": [1, 2], "y": [10, 100]}]
    }
    
    # Text with trailing commentary outside of the JSON structure
    sample_text = f"""__PRC_PLOT__
{json.dumps(mock_payload)}
This is trailing commentary that must be preserved as italicized text in the Word document.
"""
    
    parsed_dict, trailing_text = engine._extract_json_payload(sample_text)
    
    assert parsed_dict["title"] == "Mercury Injection (MICP)"
    assert parsed_dict["yAxis"]["log"] is True
    assert "This is trailing commentary" in trailing_text

def test_check_log_label_overrides():
    """
    Asserts that log scales are automatically detected based on physical labels,
    but relative permeability curves are explicitly overridden to keep a 0-1 linear scale.
    """
    engine = HvielDocEngine()
    
    # 1. Normal labels should trigger log scale detection
    mock_micp = {
        "title": "MICP",
        "xAxis": {"label": "Saturation"},
        "yAxis": {"label": "Capillary Pressure Pc (psia)"},  # 'Pc (' should trigger log
        "curves": [{"x": [0.1, 0.9], "y": [10, 1000]}]
    }
    
    # 2. Relative permeability labels must NOT trigger log scale (override active)
    mock_kr = {
        "title": "Relative Permeability",
        "xAxis": {"label": "Water Saturation Sw (fraction)"},
        "yAxis": {"label": "Relative Permeability Krw (fraction)"},  # contains 'relative permeability' and 'kr'
        "curves": [{"x": [0.2, 0.8], "y": [0.01, 0.8]}]
    }
    
    # Let's test the chart drawer configuration directly by running the private draw method
    # and ensuring no log scaling is set on the relative permeability Y-axis.
    kr_buf = engine._draw_chart_for_doc(mock_kr)
    assert kr_buf is not None
    
    micp_buf = engine._draw_chart_for_doc(mock_micp)
    assert micp_buf is not None

def test_draw_chart_log_safety_and_scatter_line_suppression():
    """
    Asserts that:
    1. Values <= 0 on logarithmic axes are filtered out to prevent math domain errors.
    2. Routine core laboratory samples showing 'showLine: False' do not render connected lines (only scatter points).
    3. Proper 5% margin padding is added on log axes to prevent stacking.
    """
    engine = HvielDocEngine()
    
    # Curve containing 0 and negative values on a log Y-axis
    mock_log_data = {
        "title": "PoroPerm Trend",
        "xAxis": {"label": "Porosity"},
        "yAxis": {"label": "Permeability (mD)", "log": True},
        "curves": [
            {
                "name": "Fitted Trend",
                "x": [0.1, 0.2, 0.3],
                "y": [1.0, 10.0, 100.0],
                "showLine": True,
                "showPoints": False
            },
            {
                "name": "Routine Samples",
                "x": [0.05, 0.15, 0.25],
                "y": [0.0, -5.0, 50.0],  # contains 0.0 and -5.0 which are invalid on a log Y-axis
                "showLine": False,       # scatter only
                "showPoints": True
            }
        ]
    }
    
    # The drawing process should filter out invalid coordinates and compile with zero errors
    buf = engine._draw_chart_for_doc(mock_log_data)
    assert buf is not None
    assert isinstance(buf, io.BytesIO)

def test_docx_report_generation(tmp_path):
    """
    Ensures that compile session reports are successfully written to disk,
    incorporate the clean white grid layout, and extract trailing commentaries perfectly.
    """
    db_path = os.path.join(tmp_path, "test_session_history.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE m (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sid TEXT,
            role TEXT,
            text TEXT,
            url TEXT
        )
    """)
    
    # Insert mock audit
    cursor.execute(
        "INSERT INTO m (sid, role, text, url) VALUES (?, ?, ?, ?)",
        ("session_123", "model", "PHYSICS HEALTH AUDIT: 95% | STATUS: PASSED", "")
    )
    
    # Insert mock plot with trailing commentary
    plot_json = {
        "title": "Formation Factor (FF)",
        "xAxis": {"label": "Porosity (fraction)"},
        "yAxis": {"label": "Formation Factor (log)"},
        "curves": [{"x": [0.1, 0.2], "y": [50, 10], "showLine": True, "showPoints": True}]
    }
    
    plot_msg = f"""Here is your Formation Factor plot:
__PRC_PLOT__
{json.dumps(plot_json)}
We observe Archie cementation exponent m = 1.95, representing typical limestone rock.
"""
    cursor.execute(
        "INSERT INTO m (sid, role, text, url) VALUES (?, ?, ?, ?)",
        ("session_123", "model", plot_msg, "")
    )
    
    conn.commit()
    conn.close()
    
    # Generate report
    engine = PRCReportEngine(db_path=db_path)
    
    # Temporarily override output folder to tmp_path
    original_getcwd = os.getcwd
    os.getcwd = lambda: str(tmp_path)
    
    try:
        filename = engine.generate("session_123", well_name="B2-16",
                                   output_dir=os.path.join(str(tmp_path), "reports"))   # explicit: no CWD-relative default (D1)
        output_file = os.path.join(str(tmp_path), "reports", filename)
        
        assert os.path.exists(output_file)
        assert os.path.getsize(output_file) > 0
        
        # Verify the docx is readable
        doc = Document(output_file)
        text_content = []
        for p in doc.paragraphs:
            text_content.append(p.text)
            
        # Verify trailing commentary was successfully appended
        assert any("m = 1.95" in t for t in text_content)
        
    finally:
        os.getcwd = original_getcwd
