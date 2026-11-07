$ErrorActionPreference = 'Stop'
$installer = Join-Path (Split-Path -Parent $PSScriptRoot) 'Instalar Job Hunting.cmd'
& $installer
exit $LASTEXITCODE
