; Inno Setup script for the VethuQ interactive shell (Windows).
; Adds vethuqic.exe to an existing VethuQ command-line install: the same folder, reusing its lib\ and
; add-ons\. It needs the VethuQ CLI installer (packages/cli/installer/vethuq-cli.iss) run first, from
; the same build: Setup refuses to run when the CLI is missing, or when the CLI's lib\ was built
; from different dependencies (lib\runtime-id.txt differs from the one this installer was built with).
;
; Only the interactive shell: no desktop app, no second copy of the command line. The CLI installer's
; uninstaller removes vethuqic.exe along with the rest of the folder.
; Built by scripts/release/release.py --interactive-cli and .github/workflows/release-interactive-cli.yml.

#define MyAppName "VethuQ"
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#ifndef MyAppNumericVersion
  #define MyAppNumericVersion "0.1.0.0"
#endif
; The id of the build's lib\ (a hash), passed in by release.py.
#ifndef RuntimeId
  #define RuntimeId "dev"
#endif
#define MyAppExeName "vethuqic.exe"
; The CLI installer's AppId (without the braces' doubling): where Windows records its install folder.
#define CliAppId "0C3F6B1E-7D52-4B8A-9E1D-5A4F2C8E7B30"

[Setup]
AppId={{6D2A9C47-3B1E-4F85-A7C0-8E5D1B3F9A62}
AppName={#MyAppName} Interactive CLI
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} Interactive CLI v{#MyAppVersion}
AppPublisher=coldsofttech
AppPublisherURL=https://github.com/coldsofttech/VethuQ
VersionInfoVersion={#MyAppNumericVersion}
LicenseFile=..\..\cli\installer\LICENSE.rtf
SetupIconFile=..\..\cli\installer\vethuq.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardImageFile=..\..\cli\installer\wizard_large.bmp
WizardSmallImageFile=..\..\cli\installer\wizard_small.bmp
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
; The CLI's folder, found in InitializeSetup.
DefaultDirName={code:CliDir}
UsePreviousAppDir=no
DisableDirPage=yes
DisableProgramGroupPage=yes
OutputDir=..\..\..\dist
OutputBaseFilename=VethuQ-Interactive-CLI-Setup
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SolidCompression=yes
#ifdef NoCompression
Compression=none
#else
Compression=lzma2/ultra64
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\..\..\build\cli\vethuq\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; A console program: Windows opens it in a terminal window.
Name: "{autoprograms}\VethuQ Interactive"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\vethuq.ico"; Comment: "Menus over the VethuQ commands"

[Tasks]
Name: "addtopath"; Description: "Add VethuQ to PATH (lets you run ""vethuqic"" from any terminal)"; GroupDescription: "Command line:"; Flags: checkedonce

[Code]
const
  CliUninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{{#CliAppId}}_is1';
  SystemEnvironmentKey = 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment';
  UserEnvironmentKey = 'Environment';

var
  FoundCliDir: string;

{ The CLI is recorded under HKCU for a per-user install and HKLM for an all-users one. Choose the same
  scope here ("Install for all users" if it was installed for all users) so Setup can write there. }
function FindCli: Boolean;
begin
  Result := RegQueryStringValue(HKCU, CliUninstallKey, 'InstallLocation', FoundCliDir);
  if not Result then
    Result := RegQueryStringValue(HKLM, CliUninstallKey, 'InstallLocation', FoundCliDir);
  if Result then
    FoundCliDir := RemoveBackslash(FoundCliDir);
end;

function CliDir(Param: string): string;
begin
  Result := FoundCliDir;
end;

function InitializeSetup: Boolean;
var
  InstalledId: AnsiString;
begin
  Result := False;
  if not FindCli or not FileExists(FoundCliDir + '\vethuq.exe') then
  begin
    SuppressibleMsgBox(
      'The VethuQ command line is not installed. Run VethuQ-CLI-Setup.exe first; this adds the ' +
      'interactive shell to the same folder.', mbError, MB_OK, IDOK);
    Exit;
  end;
  if not LoadStringFromFile(FoundCliDir + '\lib\runtime-id.txt', InstalledId) or
     (Trim(String(InstalledId)) <> '{#RuntimeId}') then
  begin
    SuppressibleMsgBox(
      'The installed VethuQ command line was built from different libraries than this installer. ' +
      'Update the VethuQ command line to the matching release first.', mbError, MB_OK, IDOK);
    Exit;
  end;
  Result := True;
end;

function EnvRootKey: Integer;
begin
  if IsAdminInstallMode then
    Result := HKEY_LOCAL_MACHINE
  else
    Result := HKEY_CURRENT_USER;
end;

function EnvironmentKey: string;
begin
  if IsAdminInstallMode then
    Result := SystemEnvironmentKey
  else
    Result := UserEnvironmentKey;
end;

function SendMessageTimeoutA(
  hWnd: Longint; Msg: Longint; wParam: Longint; lParam: AnsiString;
  fuFlags: Longint; uTimeout: Longint; var lpdwResult: Longint
): Longint;
  external 'SendMessageTimeoutA@user32.dll stdcall';

procedure RefreshEnvironment;
var
  MsgResult: Longint;
begin
  SendMessageTimeoutA(
    $FFFF { HWND_BROADCAST }, $1A { WM_SETTINGCHANGE }, 0, 'Environment',
    2 { SMTO_ABORTIFHUNG }, 2000, MsgResult
  );
end;

procedure EnvAddPath(const Path: string);
var
  Paths: string;
begin
  if not RegQueryStringValue(EnvRootKey, EnvironmentKey, 'Path', Paths) then
    Paths := '';
  if Pos(';' + Uppercase(Path) + ';', ';' + Uppercase(Paths) + ';') > 0 then
    exit;
  if (Paths <> '') and (Paths[Length(Paths)] <> ';') then
    Paths := Paths + ';';
  if RegWriteExpandStringValue(EnvRootKey, EnvironmentKey, 'Path', Paths + Path) then
    RefreshEnvironment;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('addtopath') then
    EnvAddPath(ExpandConstant('{app}'));
end;
