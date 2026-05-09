
import os
path = r'c:\Users\Asus\Downloads\scal-ai-pipeline\frontend\src\App.jsx'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix 1: Update refreshSessions to include email
import re

# Match the useCallback for refreshSessions
pattern = re.compile(r'const refreshSessions = useCallback\(async \(\) => \{(.*?)\}, \[\]\);', re.DOTALL)
replacement = r"""const refreshSessions = useCallback(async () => {
    try {
      const emailParam = user?.email ? `?email=${user.email}` : '';
      const { data } = await axios.get(`${API_URL}/api/sessions${emailParam}`);
      setSessions(data);
    } catch {}
  }, [user]);"""

content = pattern.sub(replacement, content)

# Fix 2: Add the auto-load effect
autoload_effect = """
  useEffect(() => {
    if (user?.email && !sessionId && sessions.length > 0) {
      handleLoadSession(sessions[0].id);
    }
  }, [user, sessionId, sessions]);
"""

# Find the end of the refreshSessions effect and inject after it
effect_pattern = re.compile(r'useEffect\(\(\) => \{.*?refreshSessions.*?\);', re.DOTALL)
match = effect_pattern.search(content)
if match:
    end_pos = match.end()
    content = content[:end_pos] + autoload_effect + content[end_pos:]

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated App.jsx successfully")
