param([switch]$Uninstall)
$ErrorActionPreference = 'Stop'
$id = '{A3F248D9-4C38-42DA-B020-097445264E71}'
$destination = Join-Path $env:ProgramData 'Alibre AddOns\SlidingDovetailPrototype'
$keys = @('HKLM:\SOFTWARE\Alibre Design Add-Ons', 'HKLM:\SOFTWARE\WOW6432Node\Alibre Design Add-Ons')
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (!$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run Install.cmd and approve the administrator prompt.' }
if (Get-Process -Name 'Alibre Design' -ErrorAction SilentlyContinue) { throw 'Close Alibre Design before installing or uninstalling.' }
if ($Uninstall) {
  foreach ($key in $keys) { if (Test-Path -LiteralPath $key) { Remove-ItemProperty -LiteralPath $key -Name $id -ErrorAction SilentlyContinue } }
  if (Test-Path -LiteralPath $destination) { Remove-Item -LiteralPath $destination -Recurse -Force }
  Write-Output 'Uninstalled Sliding Dovetail Joint Manager.'
  exit
}
$files = @('SlidingDovetailAddon05.dll','SlidingDovetailPrototype.adc','SlidingDovetailPrototype.ico','scripts\bootstrap.py','scripts\manager.py','scripts\dt_defaults.py','scripts\dt_form.py')
foreach ($file in $files) { if (!(Test-Path -LiteralPath (Join-Path $PSScriptRoot $file))) { throw "Missing package file: $file" } }
New-Item -ItemType Directory -Path (Join-Path $destination 'scripts') -Force | Out-Null
foreach ($file in $files) { Copy-Item -LiteralPath (Join-Path $PSScriptRoot $file) -Destination (Join-Path $destination $file) -Force }
New-Item -Path $keys[0] -Force | Out-Null
New-ItemProperty -LiteralPath $keys[0] -Name $id -Value $destination -PropertyType String -Force | Out-Null
Write-Output 'Installed v0.7.1. Restart Alibre Design.'
