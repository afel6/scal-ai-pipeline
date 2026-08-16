$git = "git"
$gh = "gh"

# Creates a PRIVATE GitHub repo — this is internal PRC code. Never --public.
# Uses your configured git identity; do not fabricate an author here.
& $git init
& $git add .
& $git commit -m "Initialize SCAL AI Pipeline"
& $gh repo create scal-ai-pipeline --private --source=. --push
Write-Output "Deployment Script Complete"
