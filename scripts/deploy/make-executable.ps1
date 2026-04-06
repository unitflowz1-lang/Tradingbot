# Make deployment scripts executable on Windows
$scripts = @(
    "build-images.sh",
    "deploy-k8s.sh", 
    "aws-deploy.sh",
    "gcp-deploy.sh"
)

foreach ($script in $scripts) {
    $path = "scripts/deploy/$script"
    if (Test-Path $path) {
        # Add execute permissions (Windows equivalent)
        $acl = Get-Acl $path
        $accessRule = New-Object System.Security.AccessControl.FileSystemAccessRule("Everyone", "FullControl", "Allow")
        $acl.SetAccessRule($accessRule)
        Set-Acl $path $acl
        Write-Host "Made $script executable"
    }
}