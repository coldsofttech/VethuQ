; Inno Setup script for VethuQ Desktop.
; Wraps the PyInstaller-built build\desktop\VethuQ\ folder into VethuQ-Setup.exe:
; VethuQ-UI.exe (desktop UI), vethuq.exe (CLI) and vethuq-worker.exe (background
; index worker the other two spawn), sharing one lib\ library folder (named
; via PyInstaller's --contents-directory in release.py, instead of its
; default "_internal").
;
; The desktop app and CLI are independently optional [Components] (the
; wizard's "Select Components" page); "core" - vethuq-worker.exe and lib\ -
; is required by both (indexing runs through it either way) and can't be
; unchecked. Since lib\ is one shared folder built from all three exes'
; PyInstaller analyses, choosing CLI-only still installs a few UI-only
; library files (sv_ttk, tcl/tk) - a few MB, not worth re-splitting the
; build to avoid.
;
; Install scope: a wizard page after the license and before Select Destination
; Location asks "Install for me only" or "Install for all users". Setup starts
; unelevated (PrivilegesRequired=lowest); choosing all users relaunches it
; elevated (/ALLUSERS, allowed via PrivilegesRequiredOverridesAllowed=commandline)
; with the license page already answered. All users needs
; administrator rights (UAC prompt) and installs to Program Files; current
; user needs none and installs to %LOCALAPPDATA%\Programs. {autopf},
; {autodesktop}, the Start menu group, the uninstall entry and the PATH
; change (HKLM vs HKCU) all follow the chosen scope, so the CLI, PATH option
; and uninstall work for both.
; Built by scripts/dev/release.py --desktop and .github/workflows/release-desktop.yml.

#define MyAppName "VethuQ"
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#define MyAppExeName "VethuQ-UI.exe"
#define MyAppCliExeName "vethuq.exe"

[Setup]
AppId={{5186479B-5A90-4D47-8626-DD8FEB85FA84}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
; Inno's default display name is "<AppName> version <AppVersion>" (shown in
; appwiz.cpl and the installer wizard); this makes it "VethuQ v<AppVersion>".
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher=coldsofttech
AppPublisherURL=https://github.com/coldsofttech/VethuQ
LicenseFile=..\..\..\LICENSE
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=..\..\..\dist
OutputBaseFilename=VethuQ-Setup
; The shared folder holds plain (uncompressed) library files, so a strong
; solid LZMA2 pass shrinks the installer far more than it could the
; already-compressed --onefile exes this replaced.
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Components]
Name: "app"; Description: "Desktop application"; Types: full desktop
Name: "cli"; Description: "Command-line interface (vethuq)"; Types: full cli
; The background index worker - both the desktop app and the CLI's "index
; run" spawn it, so it (and the library folder it needs) is required either
; way. Shown, not hidden, so it's clear why it can't be unchecked.
Name: "core"; Description: "Core runtime (required)"; Types: full desktop cli; Flags: fixed

[Types]
Name: "full"; Description: "Desktop application and CLI (recommended)"
Name: "desktop"; Description: "Desktop application only"
Name: "cli"; Description: "Command-line interface only"
Name: "custom"; Description: "Custom installation"; Flags: iscustom

[Files]
Source: "..\..\..\build\desktop\VethuQ\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion; Components: app
Source: "..\..\..\build\desktop\VethuQ\{#MyAppCliExeName}"; DestDir: "{app}"; Flags: ignoreversion; Components: cli
Source: "..\..\..\build\desktop\VethuQ\vethuq-worker.exe"; DestDir: "{app}"; Flags: ignoreversion; Components: core
Source: "..\..\..\build\desktop\VethuQ\lib\*"; DestDir: "{app}\lib"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: core

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Components: app
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; Components: app

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Components: app
Name: "addtopath"; Description: "Add VethuQ to PATH (lets you run ""vethuq"" from any terminal)"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce; Components: cli

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent; Components: app

[Code]
{ Generated from the file types' type.json files: FileTypeCount, FileTypeId/Label/Default. }
#include "filetypes.iss"

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

  if RegWriteStringValue(EnvRootKey, EnvironmentKey, 'Path', Paths) then
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

  if RegWriteStringValue(EnvRootKey, EnvironmentKey, 'Path', Paths) then
    RefreshEnvironment;
end;

var
  TypesPage: TInputOptionWizardPage;
  ScopePage: TInputOptionWizardPage;
  Relaunching: Boolean;

function TypesFile: string;
begin
  { Where VethuQ looks for the selection (the platform default data folder). }
  Result := ExpandConstant('{localappdata}\VethuQ\file_types.json');
end;

function TypesParam: string;
begin
  Result := ExpandConstant('{param:TYPES|}');
end;

function TypeWasSelected(const Id: string): Boolean;
var
  Previous: AnsiString;
begin
  { /TYPES=eml,docx wins; else the previous install's choice; else the defaults. }
  if TypesParam <> '' then
    Result := Pos(',' + Id + ',', ',' + Lowercase(TypesParam) + ',') > 0
  else if LoadStringFromFile(TypesFile, Previous) then
    Result := Pos('"' + Id + '"', Previous) > 0
  else
    Result := False;
end;

procedure InitializeWizard;
var
  I: Integer;
  Chosen: Boolean;
begin
  ScopePage := CreateInputOptionPage(wpLicense, 'Select Install Mode',
    'Who should VethuQ be installed for?',
    'VethuQ can be installed for you only, or for all users (requires administrative privileges).',
    True, False);
  ScopePage.Add('Install for me only (recommended)');
  ScopePage.Add('Install for all users');
  ScopePage.SelectedValueIndex := 0;

  TypesPage := CreateInputOptionPage(
    wpSelectComponents, 'File types',
    'Which file types should VethuQ read?',
    'Types that are not selected are not scanned or indexed. ' +
    'Run this installer again to add more later.',
    False, False
  );
  for I := 0 to FileTypeCount - 1 do
  begin
    TypesPage.Add(FileTypeLabel(I));
    Chosen := TypeWasSelected(FileTypeId(I));
    if (TypesParam = '') and (not FileExists(TypesFile)) then
      Chosen := FileTypeDefault(I);
    TypesPage.Values[I] := Chosen;
  end;
end;

procedure SaveTypeSelection;
var
  I: Integer;
  Json: string;
begin
  Json := '';
  for I := 0 to FileTypeCount - 1 do
    if TypesPage.Values[I] then
    begin
      if Json <> '' then
        Json := Json + ', ';
      Json := Json + '"' + FileTypeId(I) + '"';
    end;
  ForceDirectories(ExtractFilePath(TypesFile));
  SaveStringToFile(TypesFile, '{ "enabled": [' + Json + '] }', False);
end;

function IsRelaunched: Boolean;
begin
  Result := ExpandConstant('{param:RELAUNCHED|0}') = '1';
end;

{ Already admin (run as administrator, or /ALLUSERS) - nothing to choose. After
  the elevated relaunch the license was already answered. }
function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = ScopePage.ID then
    Result := IsAdminInstallMode
  else if IsRelaunched and (PageID = wpLicense) then
    Result := True;
end;

{ Closing for the elevated relaunch is not a user cancel - skip the prompt. }
procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
begin
  if Relaunching then
    Confirm := False;
end;

{ All users: relaunch Setup elevated and close this instance; the destination
  page then defaults to Program Files. }
function NextButtonClick(CurPageID: Integer): Boolean;
var
  Params: string;
  ResultCode: Integer;
begin
  Result := True;
  if (CurPageID = ScopePage.ID) and (ScopePage.SelectedValueIndex = 1) then
  begin
    Params := '/ALLUSERS /RELAUNCHED=1';
    if ShellExec('runas', ExpandConstant('{srcexe}'), Params, '', SW_SHOW,
      ewNoWait, ResultCode) then
    begin
      Relaunching := True;
      WizardForm.Close;
    end
    else
    begin
      MsgBox('Administrator permission was not granted, so VethuQ cannot be installed for all users.',
        mbError, MB_OK);
      Result := False;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    SaveTypeSelection;
    if WizardIsTaskSelected('addtopath') then
      EnvAddPath(ExpandConstant('{app}'));
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    EnvRemovePath(ExpandConstant('{app}'));
end;
