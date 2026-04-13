import os
from dotenv import load_dotenv
load_dotenv()

from app import AnthropicAssistant

print("Testing locally using CLAUDE_API_KEY:", repr(os.getenv('CLAUDE_API_KEY')[:15]) + "...")

try:
    history = [{"role": "user", "text": "Hello"}]
    ans = AnthropicAssistant.generate_docx(history, "Generate a tiny test report", "Test KB")
    print("SUCCESS, Claude says:", ans[:50])
except Exception as e:
    print("FAILED with Exception:", repr(e))
