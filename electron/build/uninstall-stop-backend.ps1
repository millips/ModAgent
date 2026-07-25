param(
    [Parameter(Mandatory = $true)]
    [string]$InstallDir
)

$ErrorActionPreference = 'SilentlyContinue'
$expectedPath = [IO.Path]::GetFullPath(
    (Join-Path $InstallDir 'resources\backend\ModAgentBackend.exe')
)

Get-CimInstance Win32_Process -Filter "Name = 'ModAgentBackend.exe'" |
    Where-Object {
        $_.ExecutablePath -and
        [string]::Equals(
            [IO.Path]::GetFullPath($_.ExecutablePath),
            $expectedPath,
            [StringComparison]::OrdinalIgnoreCase
        )
    } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

Start-Sleep -Milliseconds 800
