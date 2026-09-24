#define AppName "Sliding Dovetail Joint Manager"
#define AppVersion "0.8.0"
#define AppPublisher "Chris Adcock"
#define AddOnIdentifier "{{A3F248D9-4C38-42DA-B020-097445264E71}"

[Setup]
AppId={{B23B3ACB-1BFC-4AF4-A9AA-5D6590B7BAAA}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={commonappdata}\Alibre AddOns\SlidingDovetailJointManager
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=SlidingDovetailSetup-v{#AppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\SlidingDovetailJointManager.ico

[Files]
Source: "..\SlidingDovetailAddon05.dll"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\SlidingDovetailJointManager.adc"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\SlidingDovetailJointManager.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\scripts\*"; DestDir: "{app}\scripts"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Registry]
Root: HKLM; Subkey: "SOFTWARE\Alibre Design Add-Ons"; ValueType: string; ValueName: "{#AddOnIdentifier}"; ValueData: "{app}"; Flags: uninsdeletevalue

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function AlibreIsRunning(): Boolean;
var Locator, Service, Processes: Variant;
begin
  Result := False;
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Service := Locator.ConnectServer('', 'root\CIMV2');
    Processes := Service.ExecQuery('SELECT Name FROM Win32_Process WHERE Name = "Alibre Design.exe"');
    Result := Processes.Count > 0;
  except
  end;
end;

procedure RemoveLegacyDovetailCopies();
begin
  RegDeleteValue(HKLM, 'SOFTWARE\Alibre Design Add-Ons', '{A3F248D9-4C38-42DA-B020-097445264E71}');
  RegDeleteValue(HKLM, 'SOFTWARE\WOW6432Node\Alibre Design Add-Ons', '{A3F248D9-4C38-42DA-B020-097445264E71}');
  RegDeleteKeyIncludingSubkeys(HKLM, 'SOFTWARE\Alibre, LLC\Alibre Design\Addons\SlidingDovetailJointManager');
  RegDeleteKeyIncludingSubkeys(HKLM, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{A3F248D9-4C38-42DA-B020-097445264E71}_is1_is1');
  DelTree(ExpandConstant('{commonappdata}\Alibre AddOns\SlidingDovetailPrototype'), True, True, True);
  DelTree('C:\Program Files\Alibre Design\Addons\SlidingDovetailPrototype', True, True, True);
  DelTree('C:\Program Files\Alibre Design\Addons\SlidingDovetailJointManager', True, True, True);
end;

function InitializeSetup(): Boolean;
begin
  Result := not AlibreIsRunning();
  if not Result then MsgBox('Close Alibre Design, then run this installer again.', mbError, MB_OK);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  RemoveLegacyDovetailCopies();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  Result := not AlibreIsRunning();
  if not Result then MsgBox('Close Alibre Design, then uninstall again.', mbError, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then MsgBox('Installed. Start Alibre Design, open an assembly, then choose'#13#10 + 'Add-Ons > Sliding Dovetail > Joint Manager.', mbInformation, MB_OK);
end;