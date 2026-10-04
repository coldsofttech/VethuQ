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
; Languages: English is always installed; any other OCR language (Telugu today) is a page checkbox
; (or /LANGS=en,te for a silent install) recorded in %LOCALAPPDATA%\VethuQ\languages.json as
; {"enabled": [...]}. The language's OCR models are not part of the installer - they download the
; first time they are needed, or with "vethuq ocr models download --lang te".
;
; Install scope: Setup starts unelevated (PrivilegesRequired=lowest) and, because of
; PrivilegesRequiredOverridesAllowed=dialog, Inno's own first screen asks "Install for
; all users" or "Install for me only" and elevates itself when all users is chosen (UAC
; prompt, installs to Program Files); current user needs no administrator rights and installs
; to %LOCALAPPDATA%\Programs. /ALLUSERS and /CURRENTUSER skip the question. {autopf},
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
#define MyAppGuid "{5186479B-5A90-4D47-8626-DD8FEB85FA84}"
#define MySetupCopyName "VethuQ-Setup.exe"

[Setup]
AppId={{5186479B-5A90-4D47-8626-DD8FEB85FA84}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
; Inno's default display name is "<AppName> version <AppVersion>" (shown in
; appwiz.cpl and the installer wizard); this makes it "VethuQ v<AppVersion>".
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher=coldsofttech
AppPublisherURL=https://github.com/coldsofttech/VethuQ
; VethuQ's own license plus a summary of the bundled third-party licenses (not the repo LICENSE).
; LICENSE.rtf is generated from LICENSE.md (with the logo) by scripts/dev/generate_brand.py.
LicenseFile=LICENSE.rtf
; The VethuQ icon: the installer/uninstaller exe, Apps & Features, and the wizard's side and header images.
SetupIconFile=vethuq.ico
UninstallDisplayIcon={app}\vethuq-worker.exe
WizardImageFile=wizard_large.bmp
WizardSmallImageFile=wizard_small.bmp
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=..\..\..\dist
OutputBaseFilename=VethuQ-Setup
; The shared folder holds plain (uncompressed) library files, so a strong
; solid LZMA2 pass shrinks the installer far more than it could the
; already-compressed --onefile exes this replaced.
#ifdef NoCompression
; Local `release.py --desktop --dev` builds: no compression, so the build is quick and the
; installer is as large as the app.
Compression=none
#else
; Release builds: strong LZMA2, in a few parallel blocks (release.py passes the count; the
; large ultra64 dictionary uses a lot of memory per thread, so it stays small).
Compression=lzma2/ultra64
#ifndef CompressThreads
  #define CompressThreads 1
#endif
LZMANumBlockThreads={#CompressThreads}
#endif
SolidCompression=yes
LZMAUseSeparateProcess=yes
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

; Component sizes (KB) come from release.py as /DAppSizeKB= etc., because the [Files] entries carry a
; Check and so Setup cannot total them itself; without them a plain compile shows no sizes.
#ifndef AppSizeKB
  #define AppSizeKB 0
#endif
#ifndef CliSizeKB
  #define CliSizeKB 0
#endif
#ifndef CoreSizeKB
  #define CoreSizeKB 0
#endif
#define SizeBytes(KB) Str(Int(KB) * 1024)
; The label is built with #if rather than a ?: expression, which the 6.7 preprocessor rejects.
#if Int(AppSizeKB) > 0
  #define AppSizeLabel " (" + Str((Int(AppSizeKB) + 512) / 1024) + " MB)"
#else
  #define AppSizeLabel ""
#endif
#if Int(CliSizeKB) > 0
  #define CliSizeLabel " (" + Str((Int(CliSizeKB) + 512) / 1024) + " MB)"
#else
  #define CliSizeLabel ""
#endif
#if Int(CoreSizeKB) > 0
  #define CoreSizeLabel " (" + Str((Int(CoreSizeKB) + 512) / 1024) + " MB)"
#else
  #define CoreSizeLabel ""
#endif

[Components]
Name: "app"; Description: "Desktop application{#AppSizeLabel}"; Types: full desktop; ExtraDiskSpaceRequired: {#SizeBytes(AppSizeKB)}
Name: "cli"; Description: "Command-line interface (vethuq){#CliSizeLabel}"; Types: full cli; ExtraDiskSpaceRequired: {#SizeBytes(CliSizeKB)}
; The background index worker - both the desktop app and the CLI's "index
; run" spawn it, so it (and the library folder it needs) is required either
; way. Shown, not hidden, so it's clear why it can't be unchecked.
Name: "core"; Description: "Core runtime (required){#CoreSizeLabel}"; Types: full desktop cli; Flags: fixed; ExtraDiskSpaceRequired: {#SizeBytes(CoreSizeKB)}

[Types]
Name: "full"; Description: "Desktop application and CLI (recommended)"
Name: "desktop"; Description: "Desktop application only"
Name: "cli"; Description: "Command-line interface only"
Name: "custom"; Description: "Custom installation"; Flags: iscustom

[Files]
; The shortcuts point at this file, so their icon never depends on the exe's embedded one.
Source: "vethuq.ico"; DestDir: "{app}"; Flags: ignoreversion; Components: app; Check: FilesNeeded
Source: "..\..\..\build\desktop\VethuQ\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion; Components: app; Check: FilesNeeded
Source: "..\..\..\build\desktop\VethuQ\{#MyAppCliExeName}"; DestDir: "{app}"; Flags: ignoreversion; Components: cli; Check: FilesNeeded
Source: "..\..\..\build\desktop\VethuQ\vethuq-worker.exe"; DestDir: "{app}"; Flags: ignoreversion; Components: core; Check: FilesNeeded
Source: "..\..\..\build\desktop\VethuQ\lib\*"; DestDir: "{app}\lib"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: core; Check: FilesNeeded
; The Telugu fallback fonts (Noto Sans Telugu, SIL Open Font License, with its license): loaded by
; the desktop app for its own process only (vethuq_ui/fonts.py), never installed into Windows.
; Copied only when Telugu is chosen and Windows has no Telugu font of its own. Deliberately not
; tied to FilesNeeded: adding Telugu through Change copies no program files but still needs these.
Source: "..\src\vethuq_ui\assets\fonts\*"; DestDir: "{app}\fonts"; Flags: ignoreversion; Components: app; Check: TeluguFontNeeded
; Kept so Apps & Features can offer Change (the maintenance page); skipped when Setup is
; already running from that copy.
Source: "{srcexe}"; DestDir: "{app}"; DestName: "{#MySetupCopyName}"; Flags: external ignoreversion; Check: ShouldCopySetup

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\vethuq.ico"; Components: app
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\vethuq.ico"; Tasks: desktopicon; Components: app

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Components: app
Name: "addtopath"; Description: "Add VethuQ to PATH (lets you run ""vethuq"" from any terminal)"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce; Components: cli

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent; Components: app

[Code]
{ Generated from the file types' type.json files: FileTypeCount, FileTypeId/Label/Default. }
#include "filetypes.iss"
{ ...and the search engines' manifests: SearchEngineCount, SearchEngineId/Label/Default. }
#include "search_engines.iss"
{ ...and the OCR engines' and languages' manifests: OcrEngine* and Language* likewise. }
#include "ocr_engines.iss"
#include "languages.iss"

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
  EnginesPage: TInputOptionWizardPage;
  OcrPage: TInputOptionWizardPage;
  LanguagePage: TInputOptionWizardPage;

function EnginesFile: string;
begin
  Result := ExpandConstant('{localappdata}\VethuQ\search_engines.json');
end;

function EnginesParam: string;
begin
  Result := ExpandConstant('{param:ENGINES|}');
end;

function EngineWasSelected(const Id: string): Boolean;
var
  Previous: AnsiString;
begin
  { /ENGINES=exact,fuzzy wins; else the previous install's choice; else the defaults. }
  if EnginesParam <> '' then
    Result := Pos(',' + Id + ',', ',' + Lowercase(EnginesParam) + ',') > 0
  else if LoadStringFromFile(EnginesFile, Previous) then
    Result := Pos('"' + Id + '"', Previous) > 0
  else
    Result := False;
end;

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

procedure SetAllEngines(Value: Boolean);
var
  I: Integer;
begin
  for I := 0 to SearchEngineCount - 1 do
    EnginesPage.Values[I] := Value or SearchEngineDefault(I);
end;

procedure SelectAllEnginesClick(Sender: TObject);
begin
  SetAllEngines(True);
end;

procedure UnselectAllEnginesClick(Sender: TObject);
begin
  SetAllEngines(False);
end;

procedure InitEnginesPage;
var
  I: Integer;
  Chosen: Boolean;
  SelectAllButton, UnselectAllButton: TNewButton;
begin
  EnginesPage := CreateInputOptionPage(
    TypesPage.ID, 'Search engines',
    'Which search engines should VethuQ offer?',
    'Engines that are not selected are not available for searching. ' +
    'Run this installer again to add more later.',
    False, False
  );
  for I := 0 to SearchEngineCount - 1 do
  begin
    EnginesPage.Add(SearchEngineLabel(I));
    Chosen := EngineWasSelected(SearchEngineId(I));
    if (EnginesParam = '') and (not FileExists(EnginesFile)) then
      Chosen := SearchEngineDefault(I);
    { The default engine is always installed, like the default file type: ticked and locked. }
    if SearchEngineDefault(I) then
    begin
      Chosen := True;
      EnginesPage.CheckListBox.ItemEnabled[I] := False;
    end;
    EnginesPage.Values[I] := Chosen;
  end;

  { Select all / Unselect all sit under the list. }
  EnginesPage.CheckListBox.Height := EnginesPage.SurfaceHeight - ScaleY(32);

  SelectAllButton := TNewButton.Create(EnginesPage);
  SelectAllButton.Parent := EnginesPage.Surface;
  SelectAllButton.Left := 0;
  SelectAllButton.Top := EnginesPage.SurfaceHeight - ScaleY(23);
  SelectAllButton.Width := ScaleX(90);
  SelectAllButton.Height := ScaleY(23);
  SelectAllButton.Caption := 'Select all';
  SelectAllButton.OnClick := @SelectAllEnginesClick;

  UnselectAllButton := TNewButton.Create(EnginesPage);
  UnselectAllButton.Parent := EnginesPage.Surface;
  UnselectAllButton.Left := SelectAllButton.Left + SelectAllButton.Width + ScaleX(8);
  UnselectAllButton.Top := SelectAllButton.Top;
  UnselectAllButton.Width := ScaleX(90);
  UnselectAllButton.Height := ScaleY(23);
  UnselectAllButton.Caption := 'Unselect all';
  UnselectAllButton.OnClick := @UnselectAllEnginesClick;
end;

procedure SaveEngineSelection;
var
  I: Integer;
  Json: string;
begin
  Json := '';
  for I := 0 to SearchEngineCount - 1 do
    if EnginesPage.Values[I] or SearchEngineDefault(I) then
    begin
      if Json <> '' then
        Json := Json + ', ';
      Json := Json + '"' + SearchEngineId(I) + '"';
    end;
  ForceDirectories(ExtractFilePath(EnginesFile));
  SaveStringToFile(EnginesFile, '{ "enabled": [' + Json + '] }', False);
end;

function OcrFile: string;
begin
  Result := ExpandConstant('{localappdata}\VethuQ\ocr_engines.json');
end;

function LanguageFile: string;
begin
  Result := ExpandConstant('{localappdata}\VethuQ\languages.json');
end;

function LanguagesParam: string;
begin
  Result := ExpandConstant('{param:LANGS|}');
end;

function LanguageWasSelected(const Id: string): Boolean;
var
  Previous: AnsiString;
begin
  { /LANGS=en,te wins; else the previous install's choice (the older single-choice file reads as
    that one language); else just the default. }
  if LanguagesParam <> '' then
    Result := Pos(',' + Id + ',', ',' + Lowercase(LanguagesParam) + ',') > 0
  else if LoadStringFromFile(LanguageFile, Previous) then
    Result := Pos('"' + Id + '"', Previous) > 0
  else
    Result := False;
end;

function DefaultOcrIndex: Integer;
var
  I: Integer;
begin
  Result := 0;
  for I := 0 to OcrEngineCount - 1 do
    if OcrEngineDefault(I) then
    begin
      Result := I;
      Exit;
    end;
end;

procedure SetAllLanguages(Value: Boolean);
var
  I: Integer;
begin
  for I := 0 to LanguageCount - 1 do
    LanguagePage.Values[I] := Value or LanguageDefault(I);
end;

procedure SelectAllLanguagesClick(Sender: TObject);
begin
  SetAllLanguages(True);
end;

procedure UnselectAllLanguagesClick(Sender: TObject);
begin
  SetAllLanguages(False);
end;

{ The OCR engine page: single choice (radio), one engine for now. }
procedure InitOcrPage;
var
  I: Integer;
begin
  OcrPage := CreateInputOptionPage(
    wpSelectComponents, 'OCR engine',
    'Which OCR engine should VethuQ use to read scanned pages?',
    'Only one engine is available at the moment.',
    True, False
  );
  for I := 0 to OcrEngineCount - 1 do
    OcrPage.Add(OcrEngineLabel(I));
  OcrPage.SelectedValueIndex := DefaultOcrIndex;
end;

{ The languages page: English is always installed (ticked and locked, like the default file type);
  the others are optional. With more than one, which language a file is in is detected. }
procedure InitLanguagePage;
var
  I: Integer;
  Chosen: Boolean;
  SelectAllButton, UnselectAllButton: TNewButton;
begin
  LanguagePage := CreateInputOptionPage(
    OcrPage.ID, 'Languages',
    'Which languages should OCR recognise?',
    'English is always installed. With more than one language VethuQ works out which one a ' +
    'file is in. The recognition models of a language other than English download the first ' +
    'time they are needed. Run this installer again to add more later.',
    False, False
  );
  for I := 0 to LanguageCount - 1 do
  begin
    LanguagePage.Add(LanguageLabel(I));
    Chosen := LanguageWasSelected(LanguageId(I));
    if (LanguagesParam = '') and (not FileExists(LanguageFile)) then
      Chosen := LanguageDefault(I);
    if LanguageDefault(I) then
    begin
      Chosen := True;
      LanguagePage.CheckListBox.ItemEnabled[I] := False;
    end;
    LanguagePage.Values[I] := Chosen;
  end;

  { Select all / Unselect all sit under the list. }
  LanguagePage.CheckListBox.Height := LanguagePage.SurfaceHeight - ScaleY(32);

  SelectAllButton := TNewButton.Create(LanguagePage);
  SelectAllButton.Parent := LanguagePage.Surface;
  SelectAllButton.Left := 0;
  SelectAllButton.Top := LanguagePage.SurfaceHeight - ScaleY(23);
  SelectAllButton.Width := ScaleX(90);
  SelectAllButton.Height := ScaleY(23);
  SelectAllButton.Caption := 'Select all';
  SelectAllButton.OnClick := @SelectAllLanguagesClick;

  UnselectAllButton := TNewButton.Create(LanguagePage);
  UnselectAllButton.Parent := LanguagePage.Surface;
  UnselectAllButton.Left := SelectAllButton.Left + SelectAllButton.Width + ScaleX(8);
  UnselectAllButton.Top := SelectAllButton.Top;
  UnselectAllButton.Width := ScaleX(90);
  UnselectAllButton.Height := ScaleY(23);
  UnselectAllButton.Caption := 'Unselect all';
  UnselectAllButton.OnClick := @UnselectAllLanguagesClick;
end;

procedure InitOcrPages;
begin
  InitOcrPage;
  InitLanguagePage;
end;

function IsLanguageChosen(const Id: string): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 0 to LanguageCount - 1 do
    if (LanguageId(I) = Id) and (LanguagePage.Values[I] or LanguageDefault(I)) then
      Result := True;
end;

{ True when the font list under `Root` has a Telugu-capable font Windows ships (Nirmala UI on
  Windows 10 and 11; Gautami and Vani on older ones). Face names are listed as "Nirmala UI
  (TrueType)", so only the start of a name is compared. }
function RootHasTeluguFont(Root: Integer): Boolean;
var
  Names: TArrayOfString;
  I: Integer;
  Name: string;
begin
  Result := False;
  if RegGetValueNames(Root, 'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts', Names) then
    for I := 0 to GetArrayLength(Names) - 1 do
    begin
      Name := Lowercase(Names[I]);
      if (Pos('nirmala ui', Name) = 1) or (Pos('gautami ', Name) = 1) or
        (Pos('vani ', Name) = 1) then
        Result := True;
    end;
end;

{ Machine-wide, or installed for this user (Windows 10 lets a user install fonts for themselves). }
function HasNativeTeluguFont: Boolean;
begin
  Result := RootHasTeluguFont(HKEY_LOCAL_MACHINE) or RootHasTeluguFont(HKEY_CURRENT_USER);
end;

{ The fallback Telugu fonts are needed when Telugu is chosen and Windows has none of its own. }
function TeluguFontNeeded: Boolean;
begin
  Result := IsLanguageChosen('te') and not HasNativeTeluguFont;
end;

procedure SaveLanguageSelection;
var
  I: Integer;
  Json: string;
begin
  Json := '';
  for I := 0 to LanguageCount - 1 do
    if LanguagePage.Values[I] or LanguageDefault(I) then
    begin
      if Json <> '' then
        Json := Json + ', ';
      Json := Json + '"' + LanguageId(I) + '"';
    end;
  ForceDirectories(ExtractFilePath(LanguageFile));
  SaveStringToFile(LanguageFile, '{ "enabled": [' + Json + '] }', False);
end;

procedure SaveOcrSelection;
begin
  ForceDirectories(ExtractFilePath(OcrFile));
  SaveStringToFile(OcrFile,
    '{ "engine": "' + OcrEngineId(OcrPage.SelectedValueIndex) + '" }', False);
  SaveLanguageSelection;
end;

const
  MaintChange = 0;
  MaintRepair = 1;
  MaintUninstall = 2;

var
  MaintPage: TInputOptionWizardPage;
  Quitting: Boolean;
  ChangeChosen: Boolean;
  PreviousSize: Cardinal;

function UninstallKey: string;
begin
  Result := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppGuid}_is1';
end;

{ The registry root VethuQ is installed under (HKLM for all users, HKCU for one user), if any. }
function InstalledRoot(var Root: Integer): Boolean;
begin
  Result := True;
  if RegKeyExists(HKEY_LOCAL_MACHINE, UninstallKey) then
    Root := HKEY_LOCAL_MACHINE
  else if RegKeyExists(HKEY_CURRENT_USER, UninstallKey) then
    Root := HKEY_CURRENT_USER
  else
    Result := False;
end;

function AlreadyInstalled: Boolean;
var
  Root: Integer;
begin
  Result := InstalledRoot(Root);
end;

function ListHas(const List, Name: string): Boolean;
begin
  Result := Pos(',' + Name + ',', ',' + List + ',') > 0;
end;

{ True when the components ticked now are exactly those the installed copy was set up with. }
function SameComponentsAsInstalled: Boolean;
var
  Root: Integer;
  Previous: string;
begin
  Result := False;
  if InstalledRoot(Root) and
    RegQueryStringValue(Root, UninstallKey, 'Inno Setup: Selected Components', Previous) then
    Result :=
      (ListHas(Previous, 'app') = WizardIsComponentSelected('app')) and
      (ListHas(Previous, 'cli') = WizardIsComponentSelected('cli')) and
      (ListHas(Previous, 'core') = WizardIsComponentSelected('core'));
end;

{ Change on the same version with the same components: only the file types and search engines selection (and the
  tasks) differ, so no program files need copying - they are all bundled already. A silent
  run or a newer Setup never takes this path, so upgrades always install the files. }
function TypesOnly: Boolean;
var
  Root: Integer;
  Version: string;
begin
  Result := False;
  if ChangeChosen and InstalledRoot(Root) and
    RegQueryStringValue(Root, UninstallKey, 'DisplayVersion', Version) and
    (Version = '{#MyAppVersion}') then
    Result := SameComponentsAsInstalled;
end;

function FilesNeeded: Boolean;
begin
  Result := not TypesOnly;
end;

{ Copy Setup into the app folder for Apps & Features' Change button, unless it is already
  running from there. A types-only change copies it only when it is missing. }
function ShouldCopySetup: Boolean;
var
  Copy: string;
begin
  Copy := ExpandConstant('{app}\{#MySetupCopyName}');
  Result := CompareText(ExpandConstant('{srcexe}'), Copy) <> 0;
  if Result and TypesOnly then
    Result := not FileExists(Copy);
end;

procedure RunUninstaller;
var
  Root, ResultCode: Integer;
  Command: string;
begin
  if InstalledRoot(Root) and
    RegQueryStringValue(Root, UninstallKey, 'UninstallString', Command) then
  begin
    Quitting := True;
    Exec(RemoveQuotes(Command), '', '', SW_SHOW, ewNoWait, ResultCode);
    WizardForm.Close;
  end;
end;

procedure SetAllTypes(Value: Boolean);
var
  I: Integer;
begin
  for I := 0 to FileTypeCount - 1 do
    TypesPage.Values[I] := Value or FileTypeDefault(I);
end;

procedure SelectAllTypesClick(Sender: TObject);
begin
  SetAllTypes(True);
end;

procedure UnselectAllTypesClick(Sender: TObject);
begin
  SetAllTypes(False);
end;

procedure InitializeWizard;
var
  I: Integer;
  Chosen: Boolean;
  SelectAllButton, UnselectAllButton: TNewButton;
begin
  { Shown first when VethuQ is already installed. }
  MaintPage := CreateInputOptionPage(wpWelcome, 'VethuQ is already installed',
    'What would you like to do?',
    'Choose Change to pick different components or file types, or Repair to reinstall ' +
    'VethuQ''s files. Your indexed data and settings are kept either way.',
    True, False);
  MaintPage.Add('Change - choose different components or file types');
  MaintPage.Add('Repair - reinstall VethuQ''s files');
  MaintPage.Add('Uninstall VethuQ');
  MaintPage.SelectedValueIndex := MaintChange;

  InitOcrPages;

  TypesPage := CreateInputOptionPage(
    LanguagePage.ID, 'File types',
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
    { The default type (PDF) is always installed, like the core runtime: ticked and locked. }
    if FileTypeDefault(I) then
    begin
      Chosen := True;
      TypesPage.CheckListBox.ItemEnabled[I] := False;
    end;
    TypesPage.Values[I] := Chosen;
  end;

  { Select all / Unselect all sit under the list. }
  TypesPage.CheckListBox.Height := TypesPage.SurfaceHeight - ScaleY(32);

  SelectAllButton := TNewButton.Create(TypesPage);
  SelectAllButton.Parent := TypesPage.Surface;
  SelectAllButton.Left := 0;
  SelectAllButton.Top := TypesPage.SurfaceHeight - ScaleY(23);
  SelectAllButton.Width := ScaleX(90);
  SelectAllButton.Height := ScaleY(23);
  SelectAllButton.Caption := 'Select all';
  SelectAllButton.OnClick := @SelectAllTypesClick;

  UnselectAllButton := TNewButton.Create(TypesPage);
  UnselectAllButton.Parent := TypesPage.Surface;
  UnselectAllButton.Left := SelectAllButton.Left + SelectAllButton.Width + ScaleX(8);
  UnselectAllButton.Top := SelectAllButton.Top;
  UnselectAllButton.Width := ScaleX(90);
  UnselectAllButton.Height := ScaleY(23);
  UnselectAllButton.Caption := 'Unselect all';
  UnselectAllButton.OnClick := @UnselectAllTypesClick;

  InitEnginesPage;
end;

{ Adds the chosen file types and search engines to the Ready to Install summary, after the tasks. }
function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
var
  I: Integer;
  Types, Engines, Languages: string;
begin
  Types := '';
  for I := 0 to FileTypeCount - 1 do
    if TypesPage.Values[I] then
      Types := Types + Space + Space + FileTypeLabel(I) + NewLine;
  if Types = '' then
    Types := Space + Space + 'None' + NewLine;

  Engines := '';
  for I := 0 to SearchEngineCount - 1 do
    if EnginesPage.Values[I] or SearchEngineDefault(I) then
      Engines := Engines + Space + Space + SearchEngineLabel(I) + NewLine;

  Languages := '';
  for I := 0 to LanguageCount - 1 do
    if LanguagePage.Values[I] or LanguageDefault(I) then
      Languages := Languages + Space + Space + LanguageLabel(I) + NewLine;

  Result := '';
  if TypesOnly then
    Result := 'No program files will be copied - only your choices are updated.' + NewLine + NewLine;
  if MemoDirInfo <> '' then Result := Result + MemoDirInfo + NewLine + NewLine;
  if MemoTypeInfo <> '' then Result := Result + MemoTypeInfo + NewLine + NewLine;
  if MemoComponentsInfo <> '' then Result := Result + MemoComponentsInfo + NewLine + NewLine;
  if MemoGroupInfo <> '' then Result := Result + MemoGroupInfo + NewLine + NewLine;
  if MemoTasksInfo <> '' then Result := Result + MemoTasksInfo + NewLine + NewLine;
  Result := Result + 'OCR engine:' + NewLine + Space + Space +
    OcrEngineLabel(OcrPage.SelectedValueIndex) + NewLine + NewLine;
  Result := Result + 'Languages:' + NewLine + Languages + NewLine;
  Result := Result + 'File types:' + NewLine + Types + NewLine;
  Result := Result + 'Search engines:' + NewLine + Engines;
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

{ On a re-run the license was already accepted; Repair keeps the previous choices, so it
  goes straight to the summary. }
function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = MaintPage.ID then
    Result := not AlreadyInstalled
  else if AlreadyInstalled then
  begin
    if PageID = wpLicense then
      Result := True
    else if MaintPage.SelectedValueIndex = MaintRepair then
      Result := (PageID = wpSelectComponents) or (PageID = OcrPage.ID) or
        (PageID = LanguagePage.ID) or (PageID = TypesPage.ID) or
        (PageID = EnginesPage.ID) or (PageID = wpSelectTasks);
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = MaintPage.ID then
    ChangeChosen := MaintPage.SelectedValueIndex = MaintChange;
  if (CurPageID = MaintPage.ID) and (MaintPage.SelectedValueIndex = MaintUninstall) then
  begin
    RunUninstaller;
    Result := False;
  end;
end;

{ Closing to hand over to the uninstaller is not a user cancel - skip the prompt. }
procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
begin
  if Quitting then
    Confirm := False;
end;

{ Apps & Features: a Change button that re-runs the kept copy of Setup. A types-only change
  copies nothing, so Setup would store a tiny size; keep the one from the earlier install. }
procedure RegisterChange;
begin
  if TypesOnly and (PreviousSize > 0) then
    RegWriteDWordValue(EnvRootKey, UninstallKey, 'EstimatedSize', PreviousSize);
  RegWriteStringValue(EnvRootKey, UninstallKey, 'ModifyPath',
    '"' + ExpandConstant('{app}\{#MySetupCopyName}') + '"');
  RegWriteDWordValue(EnvRootKey, UninstallKey, 'NoModify', 0);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    { Read before Setup rewrites the uninstall entry at the end of the install. }
    if not RegQueryDWordValue(EnvRootKey, UninstallKey, 'EstimatedSize', PreviousSize) then
      PreviousSize := 0;
  end;
  if CurStep = ssPostInstall then
  begin
    SaveOcrSelection;
    SaveTypeSelection;
    SaveEngineSelection;
    if WizardIsTaskSelected('addtopath') then
      EnvAddPath(ExpandConstant('{app}'));
  end
  else if CurStep = ssDone then
    RegisterChange;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    EnvRemovePath(ExpandConstant('{app}'));
end;
