$git = "git"
$gh = "gh"

& $git init
& $git config user.name "AI Pipeline"
& $git config user.email "ai@example.com"
& $git add .
& $git commit -m "Initialize SCAL AI Pipeline"
& $gh repo create scal-ai-pipeline --public --source=. --push
Write-Output "Deployment Script Complete"
