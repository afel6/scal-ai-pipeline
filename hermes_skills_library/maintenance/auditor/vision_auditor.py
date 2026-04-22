import os
import sys
import json
import base64
from google import genai
from google.genai import types

def audit_image(image_path, manual_context, query):
    """
    Performs a visual audit of a device setup against its manual instructions.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return {"error": "GEMINI_API_KEY not found in environment."}

    client = genai.Client(api_key=api_key)
    
    with open(image_path, "rb") as f:
        image_data = f.read()

    prompt = f"""
    You are a Senior Laboratory Auditor for the Petroleum Research Center (PRC).
    
    CONTEXT FROM MANUALS:
    {manual_context}
    
    USER QUERY/PROBLEM:
    {query}
    
    TASK:
    1. Analyze the attached photo of the laboratory equipment.
    2. Identify the device and its current configuration (valves, dials, connections).
    3. Compare this configuration against the 'Gold Standard' maintenance and operation instructions provided in the context.
    4. DETECT ERRORS: Point out exactly where the technician made a mistake (e.g., 'Valve A is Open but should be Closed').
    5. NEXT STEP: Tell the user what they must do next to correct the state or proceed with the experiment.
    6. MAINTENANCE: Provide specific maintenance advice if the equipment looks worn or improperly serviced.
    
    Format your response in professional Markdown with clear headings. Use 'ERROR DETECTED' in red/bold if a mistake is found.
    """

    response = client.models.generate_content(
        model="gemini-1.5-pro",
        contents=[
            prompt,
            types.Part.from_bytes(data=image_data, mime_type="image/jpeg")
        ]
    )

    return {"result": response.text}

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(json.dumps({"error": "Usage: python vision_auditor.py <image_path> <manual_context> <query>"}))
        sys.exit(1)

    img_path = sys.argv[1]
    ctx = sys.argv[2]
    q = sys.argv[3]
    
    try:
        res = audit_image(img_path, ctx, q)
        print(json.dumps(res))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
