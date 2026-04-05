from hviel_doc_engine import HvielDocEngine
import json

raw_json = '''{
    "title": "Test",
    "sections": [
        {
            "heading": "Data",
            "level": 1,
            "paragraphs": [
                "Some introductory text.",
                "| Sample # | Porosity | Permeability | Formation Factor |",
                "|:---------|:--------------------|:------------------|:-----------------|",
                "| 31       | 0.1830              | 52.315            | 32.328           |",
                "Some trailing text."
            ]
        }
    ]
}'''

engine = HvielDocEngine()
print('Testing interceptor...')
try:
    out = engine.build_from_json(raw_json, 'docx')
    print('Built docx successfully at:', out)
except Exception as e:
    print('ERROR:', e)
