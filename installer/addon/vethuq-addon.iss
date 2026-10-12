; Inno Setup script for one VethuQ add-on or bundle (Windows). One script serves them all; release.py
; passes
;   /DPackageId=xls            the add-on's name, or bundle-office for a bundle
;   /DPackageTitle="add-on xls"  what the messages call it ("bundle office" for a bundle)
;   /DPackageGuid=...          its AppId (derived from the name, so every add-on and bundle installs and
;                              uninstalls on its own)
;   /DOutputName=...           the installer's file name
;   /DStageDir=...             a tree that mirrors VethuQ's folder: add-ons\<name>\ for every add-on
;                              (its package and its dist-info, which holds the entry point VethuQ finds
;                              it by; a bundle also has add-ons\bundle-<name>\) and lib\ for the
;                              packages they need that VethuQ does not already carry
;   /DMyAppVersion, /DMyAppNumericVersion
;
; Everything is installed into <VethuQ folder>, where VethuQ puts every add-ons\ folder on sys.path: no
; PyInstaller step, an add-on is compiled modules and a few packages. The dependencies go into the shared
; lib\ (the same place the default add-ons' dependencies are), at the versions pinned in
; installer\addon\constraints.txt so every add-on agrees on one. All of it is installed as Inno shared
; files: Windows counts how many installers put each file there, so an add-on installed alone and again
; by a bundle (or two bundles that share one, like json in web and developer) is removed only with the last.
; VethuQ must be installed first (the command line, the interactive shell or the desktop app): Setup says
; so and stops otherwise. Setup starts unelevated and asks "Install for all users" or "Install for me
; only", like the main installers; use the same choice as VethuQ was installed with so Setup can write to
; its folder. Licences are not asked for here: a licensed add-on is activated with the command line
; (vethuq settings addons <name> licence <token>).
; Built by scripts/release/release.py --add-on / --bundle and .github/workflows/release-add-on.yml /
; release-bundle.yml.

#ifndef PackageId
  #error PackageId is not set (release.py passes /DPackageId=<name>)
#endif
#ifndef PackageTitle
  #error PackageTitle is not set
#endif
#ifndef PackageGuid
  #error PackageGuid is not set
#endif
#ifndef OutputName
  #error OutputName is not set
#endif
#ifndef StageDir
  #error StageDir is not set
#endif
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#ifndef MyAppNumericVersion
  #define MyAppNumericVersion "0.1.0.0"
#endif

[Setup]
AppId={{{#PackageGuid}}
AppName=VethuQ {#PackageTitle}
AppVersion={#MyAppVersion}
AppVerName=VethuQ {#PackageTitle} v{#MyAppVersion}
AppPublisher=coldsofttech
AppPublisherURL=https://github.com/coldsofttech/VethuQ
VersionInfoVersion={#MyAppNumericVersion}
LicenseFile=..\shared\LICENSE.rtf
SetupIconFile=..\shared\vethuq.ico
WizardImageFile=..\shared\wizard_large.bmp
WizardSmallImageFile=..\shared\wizard_small.bmp
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
; VethuQ's folder, found in InitializeSetup.
DefaultDirName={code:VethuqDir}
UsePreviousAppDir=no
DisableDirPage=yes
DisableProgramGroupPage=yes
OutputDir=..\..\dist
OutputBaseFilename={#OutputName}
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
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs sharedfile uninsnosharedfileprompt

[Code]
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\';
  { The AppIds of the installers that put VethuQ on a computer: the command line, the interactive
    shell, and the desktop app. }
  CliKey = '{0C3F6B1E-7D52-4B8A-9E1D-5A4F2C8E7B30}_is1';
  ShellKey = '{6D2A9C47-3B1E-4F85-A7C0-8E5D1B3F9A62}_is1';
  DesktopKey = '{5186479B-5A90-4D47-8626-DD8FEB85FA84}_is1';

var
  FoundDir: string;

function InstallLocation(const Key: string): Boolean;
begin
  Result := RegQueryStringValue(HKCU, UninstallKey + Key, 'InstallLocation', FoundDir);
  if not Result then
    Result := RegQueryStringValue(HKLM, UninstallKey + Key, 'InstallLocation', FoundDir);
  if Result then
    FoundDir := RemoveBackslash(FoundDir);
  Result := Result and DirExists(FoundDir);
end;

function VethuqDir(Param: string): string;
begin
  Result := FoundDir;
end;

function InitializeSetup: Boolean;
begin
  Result := InstallLocation(CliKey) or InstallLocation(ShellKey) or InstallLocation(DesktopKey);
  if not Result then
    SuppressibleMsgBox(
      'VethuQ is not installed. Install VethuQ first (VethuQ-CLI-Setup.exe, the interactive shell or ' +
      'the desktop app), then run this setup again to add the {#PackageTitle}.',
      mbError, MB_OK, IDOK);
end;
