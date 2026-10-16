; Inno Setup script for the VethuQ background service (Windows).
; Adds vethuqbs.exe, and the `vethuq background ...` commands, to an existing VethuQ command-line
; install: the same folder as vethuq.exe and vethuqic.exe, reusing its lib\ and add-ons\. Like the
; interactive shell's installer it needs the CLI installer run first, from the same build (see
; installer\shared\into_cli_folder.iss).
;
; Only the background service: no desktop app, no command line, no shell. vethuqbs.exe is the program
; the Windows service runs (it hosts itself in the service manager); the `vethuq background` commands
; live in add-ons\background\ (the vethuq_background package and its entry point), which is how the
; command line and the shell find them.
;
; Setup does NOT create the Windows service, in either install scope. Creating one needs administrator
; rights and a Windows account (with its password) to run as, which is a deliberate choice rather than a
; default, so it is done afterwards with "vethuq background install" (AFTER_INSTALL.txt says so). If the
; service is installed, Setup stops it while it replaces vethuqbs.exe (which the service runs) and starts
; it again afterwards, and uninstalling removes it.
; Built by scripts/release/release.py --background-service and
; .github/workflows/release-background-service.yml.

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
#define MyAppExeName "vethuqbs.exe"
#define ProgramName "background service"
; The CLI installer's AppId: where Windows records its install folder.
#define CliAppId "0C3F6B1E-7D52-4B8A-9E1D-5A4F2C8E7B30"

[Setup]
AppId={{B7E41D93-2A6C-4C0F-8D15-3F9A7E6B2C48}
AppName={#MyAppName} Background Service
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} Background Service v{#MyAppVersion}
AppPublisher=coldsofttech
AppPublisherURL=https://github.com/coldsofttech/VethuQ
VersionInfoVersion={#MyAppNumericVersion}
LicenseFile=..\..\..\installer\shared\LICENSE.rtf
InfoAfterFile=AFTER_INSTALL.txt
SetupIconFile=..\..\..\installer\shared\vethuq.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardImageFile=..\..\..\installer\shared\wizard_large.bmp
WizardSmallImageFile=..\..\..\installer\shared\wizard_small.bmp
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
; The CLI's folder, found in InitializeSetup.
DefaultDirName={code:CliDir}
UsePreviousAppDir=no
DisableDirPage=yes
DisableProgramGroupPage=yes
OutputDir=..\..\..\dist
OutputBaseFilename=VethuQ-Background-Service-Setup
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

[Dirs]
; The device folder: licences and the credit ledger, shared by every account on this computer and by
; the background service (see vethuq._paths.device). An all-users install creates it here, open to
; the Users group; a per-user install can't, so VethuQ makes it on first use if the account may, and
; otherwise keeps those in the account's own data folder. Never removed by an uninstall, so
; reinstalling does not hand out a fresh allowance.
Name: "{commonappdata}\VethuQ"; Permissions: users-modify; Flags: uninsneveruninstall; Check: IsAdminInstallMode

[Files]
Source: "..\..\..\build\cli\vethuq\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; The `vethuq background` commands: the package and its dist-info (its entry point), staged by release.py.
Source: "..\..\..\build\cli\background-plugin\*"; DestDir: "{app}\add-ons\background"; Flags: ignoreversion recursesubdirs createallsubdirs

[Code]
#include "..\..\..\installer\shared\into_cli_folder.iss"

const
  ServiceName = 'VethuQBackground';

var
  ServiceWasRunning: Boolean;

{ Runs sc.exe, elevated through UAC when Setup is not already running as administrator. Returns its
  exit code, or -1 if it did not run. }
function RunSc(const Params: string): Integer;
var
  ResultCode: Integer;
  Sc: string;
begin
  Result := -1;
  Sc := ExpandConstant('{sys}\sc.exe');
  if IsAdminInstallMode then
  begin
    if Exec(Sc, Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      Result := ResultCode;
  end
  else if ShellExec('runas', Sc, Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Result := ResultCode;
end;

{ sc.exe exits 0 when the service exists (a query needs no elevation). }
function ServiceInstalled: Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(ExpandConstant('{sys}\sc.exe'), 'query ' + ServiceName, '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function ServiceRunning: Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(ExpandConstant('{cmd}'), '/C sc query ' + ServiceName + ' | find "RUNNING"', '',
    SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

{ Waits (up to about 30 seconds) for the service to stop, so its program can be replaced or deleted. }
procedure WaitUntilStopped;
var
  Waited: Integer;
begin
  Waited := 0;
  while ServiceRunning and (Waited < 60) do
  begin
    Sleep(500);
    Waited := Waited + 1;
  end;
end;

function InitializeSetup: Boolean;
begin
  Result := CliFolderReady;
end;

{ The service runs vethuqbs.exe, which Setup is about to replace: stop it first, and
  (CurStepChanged) start it again afterwards if it was running. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  ServiceWasRunning := ServiceInstalled and ServiceRunning;
  if ServiceWasRunning then
  begin
    RunSc('stop ' + ServiceName);
    WaitUntilStopped;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and ServiceWasRunning then
    RunSc('start ' + ServiceName);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usUninstall) and ServiceInstalled then
  begin
    { Before the files go: the service holds vethuqbs.exe open. }
    RunSc('stop ' + ServiceName);
    WaitUntilStopped;
    RunSc('delete ' + ServiceName);
  end;
end;
