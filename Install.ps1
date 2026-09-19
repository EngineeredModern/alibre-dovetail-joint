param([switch]$Uninstall)
$ErrorActionPreference = 'Stop'
$id = '{A3F248D9-4C38-42DA-B020-097445264E71}'
$destination = Join-Path $env:ProgramData 'Alibre AddOns\SlidingDovetailPrototype'
$key = 'HKLM:\SOFTWARE\Alibre Design Add-Ons'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (!$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run Install.cmd and approve the administrator prompt.' }
if (Get-Process -Name 'Alibre Design' -ErrorAction SilentlyContinue) { throw 'Close Alibre Design before installing.' }
if ($Uninstall) { Remove-ItemProperty -LiteralPath $key -Name $id -ErrorAction SilentlyContinue; exit }
$files = @('SlidingDovetailAddon05.dll','SlidingDovetailPrototype.adc','SlidingDovetailPrototype.ico','scripts\bootstrap.py','scripts\manager.py','scripts\dt_defaults.py','scripts\dt_form.py')
foreach ($file in $files) { if (!(Test-Path -LiteralPath (Join-Path $PSScriptRoot $file))) { throw "Missing package file: $file" } }
New-Item -ItemType Directory -Path (Join-Path $destination 'scripts') -Force | Out-Null
foreach ($file in $files) { Copy-Item -LiteralPath (Join-Path $PSScriptRoot $file) -Destination (Join-Path $destination $file) -Force }
New-Item -Path $key -Force | Out-Null
New-ItemProperty -LiteralPath $key -Name $id -Value $destination -PropertyType String -Force | Out-Null
Write-Output 'Installed v0.7.1. Restart Alibre Design.'
