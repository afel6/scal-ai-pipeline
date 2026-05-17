REM Portability fix: only inject Git path if not already available
WHERE git >nul 2>&1 || SET PATH=C:\Program Files\Git\cmd;%PATH%
git add .
git commit -m "Conversational AI Architecture: Full Multi-Modal PRC Chat Hub Deployed"
git push
