; Inno Setup script for the VethuQ command line (Windows).
; Wraps the PyInstaller-built build\cli\vethuq\ folder into VethuQ-CLI-Setup.exe:
;
;   vethuq.exe   the command
;   lib\         the Python runtime and every dependency (Paddle, rich, SQLAlchemy, ...)
;   add-ons\     the default add-ons, one folder each (pdf\, like\, ...)
;
; Only the command line: no desktop app, no interactive shell, no background service. The OCR
; models are not part of the installer; Paddle downloads them the first time OCR runs.
;
; Install scope: Setup starts unelevated (PrivilegesRequired=lowest) and, because of
; PrivilegesRequiredOverridesAllowed=dialog, Inno's first screen asks "Install for all users" or
; "Install for me only" and elevates itself when all users is chosen. {autopf}, the uninstall entry
; and the PATH change (HKLM vs HKCU) follow the chosen scope. /ALLUSERS and /CURRENTUSER skip the
; question; /TASKS="addtopath" or /MERGETASKS="!addtopath" decide the PATH change when silent.
; Built by scripts/release/release.py --cli and .github/workflows/release-cli.yml.

#define MyAppName "VethuQ"
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#define MyAppExeName "vethuq.exe"
; Numeric a.b.c.d for the file's version info (MyAppVersion may carry a pre-release suffix).
#ifndef MyAppNumericVersion
  #define MyAppNumericVersion "0.1.0.0"
#endif

[Setup]
; A GUID of its own: the CLI installs and uninstalls independently of any other VethuQ installer.
AppId={{0C3F6B1E-7D52-4B8A-9E1D-5A4F2C8E7B30}
AppName={#MyAppName} CLI
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} CLI v{#MyAppVersion}
AppPublisher=coldsofttech
AppPublisherURL=https://github.com/coldsofttech/VethuQ
VersionInfoVersion={#MyAppNumericVersion}
LicenseFile=..\..\..\installer\shared\LICENSE.rtf
InfoAfterFile=AFTER_INSTALL.txt
; The VethuQ icon: the installer/uninstaller exe, Apps & Features, and the wizard's side and header images.
SetupIconFile=..\..\..\installer\shared\vethuq.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardImageFile=..\..\..\installer\shared\wizard_large.bmp
WizardSmallImageFile=..\..\..\installer\shared\wizard_small.bmp
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\..\..\dist
OutputBaseFilename=VethuQ-CLI-Setup
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SolidCompression=yes
LZMAUseSeparateProcess=yes
#ifdef NoCompression
; Local `release.py --cli --dev` builds: no compression, so the build is quick.
Compression=none
#else
; The folder holds plain library files, so a strong solid LZMA2 pass shrinks it a lot.
Compression=lzma2/ultra64
#ifndef CompressThreads
  #define CompressThreads 1
#endif
LZMANumBlockThreads={#CompressThreads}
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Dirs]
; The device folder: licences and the credit ledger, shared by every account on this computer and by
; the background service (see vethuq._paths.device). An all-users install creates it here, open to
; the Users group; a per-user install can't, so VethuQ makes it on first use if the account may, and
; otherwise keeps those in the account's own data folder. Never removed by an ordinary uninstall, so
; reinstalling does not hand out a fresh allowance; only the uninstaller's "remove all VethuQ data"
; choice (or /REMOVEDATA=1 when silent) removes it. See docs/device-folder.md.
Name: "{commonappdata}\VethuQ"; Permissions: users-modify; Flags: uninsneveruninstall; Check: IsAdminInstallMode

[Files]
Source: "..\..\..\installer\shared\vethuq.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\..\build\cli\vethuq\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\..\build\cli\vethuq\lib\*"; DestDir: "{app}\lib"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\..\build\cli\vethuq\add-ons\*"; DestDir: "{app}\add-ons"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; The Start menu folder (Start > Programs > VethuQ) is shared with the other installers; each removes only its own shortcuts.
; Only an uninstall shortcut: removing the command line removes the whole folder, the other VethuQ programs in it included.
Name: "{autoprograms}\VethuQ\Uninstall VethuQ CLI"; Filename: "{uninstallexe}"; IconFilename: "{app}\vethuq.ico"; Comment: "Remove the VethuQ command line"

[UninstallDelete]
; The interactive shell, the background service and the worker (their own installers) live in this folder and rely
; on lib\.
Type: files; Name: "{app}\vethuqic.exe"
Type: files; Name: "{app}\vethuqbs.exe"
Type: files; Name: "{app}\vethuqw.exe"
Type: files; Name: "{app}\unins001.*"
Type: files; Name: "{app}\unins002.*"
Type: files; Name: "{app}\unins003.*"
; Add-ons put their own folders in add-ons\ and their dependencies in lib\ (Inno shared files): they go
; with VethuQ, so nothing is left behind if the command line is removed first.
Type: filesandordirs; Name: "{app}\add-ons"
Type: filesandordirs; Name: "{app}\lib"

[Tasks]
Name: "addtopath"; Description: "Add VethuQ to PATH (lets you run ""vethuq"" from any terminal)"; GroupDescription: "Command line:"; Flags: checkedonce

[Code]
#include "..\..\..\installer\shared\background_service.iss"

const
  SystemEnvironmentKey = 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment';
  UserEnvironmentKey = 'Environment';

{ PATH lives in HKLM for an all-users install, HKCU for a per-user one.
  IsAdminInstallMode is also valid while uninstalling (it reflects the scope
  the app was installed in). }
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

function EnvPathContains(const Paths, Path: string): Boolean;
begin
  Result := Pos(';' + Uppercase(Path) + ';', ';' + Uppercase(Paths) + ';') > 0;
end;

procedure EnvAddPath(const Path: string);
var
  Paths: string;
begin
  if not RegQueryStringValue(EnvRootKey, EnvironmentKey, 'Path', Paths) then
    Paths := '';

  if EnvPathContains(Paths, Path) then
    exit;

  if (Paths <> '') and (Paths[Length(Paths)] <> ';') then
    Paths := Paths + ';';
  Paths := Paths + Path;

  if RegWriteExpandStringValue(EnvRootKey, EnvironmentKey, 'Path', Paths) then
    RefreshEnvironment;
end;

procedure EnvRemovePath(const Path: string);
var
  Paths: string;
  P: Integer;
begin
  if not RegQueryStringValue(EnvRootKey, EnvironmentKey, 'Path', Paths) then
    exit;

  P := Pos(';' + Uppercase(Path) + ';', ';' + Uppercase(Paths) + ';');
  if P = 0 then
    exit;

  Delete(Paths, P - 1, Length(Path) + 1);

  if RegWriteExpandStringValue(EnvRootKey, EnvironmentKey, 'Path', Paths) then
    RefreshEnvironment;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('addtopath') then
    EnvAddPath(ExpandConstant('{app}'));
end;

var
  RemoveAllData: Boolean;

{ Whether to remove all VethuQ data too: asked once, default No. /REMOVEDATA=1 says yes without asking
  (a silent uninstall never shows the question). }
function InitializeUninstall: Boolean;
begin
  Result := True;
  RemoveAllData := ExpandConstant('{param:REMOVEDATA|0}') = '1';
  if not RemoveAllData then
    RemoveAllData := SuppressibleMsgBox(
      'Also remove all VethuQ data?' + #13#10 + #13#10 +
      'This deletes your licences and credit history (shared by every account on this computer), ' +
      'and this account''s database, settings, logs, downloaded OCR models and add-on data. ' +
      'It cannot be undone, and reinstalling would start with a fresh allowance.' + #13#10 + #13#10 +
      'Choose No to keep them: a later install picks up where this one left off.',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES;
end;

{ What "all VethuQ data" is: the device folder (licences and the credit ledger) and this account's data
  folder (database, settings, logs, OCR models, add-on data). Another account's data folder, and a
  data folder moved elsewhere on purpose (VETHUQ_HOME or `vethuq settings location set`), are left
  alone. The device folder needs the rights it was created with: a per-user uninstall may not have them. }
procedure RemoveVethuQData;
var
  Device: string;
begin
  Device := ExpandConstant('{commonappdata}\VethuQ');
  DelTree(ExpandConstant('{localappdata}\VethuQ'), True, True, True);
  DelTree(ExpandConstant('{userappdata}\VethuQ'), True, True, True);
  if DirExists(Device) and not DelTree(Device, True, True, True) then
    SuppressibleMsgBox(
      'The licences and credit history in ' + Device + ' could not be removed. Uninstall VethuQ for ' +
      'all users, or delete that folder as an administrator.',
      mbInformation, MB_OK, IDOK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    { The service runs vethuqbs.exe from this folder: stop and remove it before the files go. }
    RemoveService;
    EnvRemovePath(ExpandConstant('{app}'));
  end
  else if (CurUninstallStep = usPostUninstall) and RemoveAllData then
    RemoveVethuQData;
end;
