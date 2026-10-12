{ Shared by the installers that go into the command line's folder (the interactive shell and the
  background service). #included in [Code], after these are defined:
    CliAppId     the command line installer's AppId (without braces)
    RuntimeId    the id of the lib\ this installer was built with
    ProgramName  what this installer adds, for the messages ("interactive shell")
  Use DefaultDirName={code:CliDir}, call CliFolderReady from InitializeSetup, and EnvAddPath from the
  PATH task. }
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

function CliFolderReady: Boolean;
var
  InstalledId: AnsiString;
begin
  Result := False;
  if not FindCli or not FileExists(FoundCliDir + '\vethuq.exe') then
  begin
    SuppressibleMsgBox(
      'The VethuQ command line is not installed. Run VethuQ-CLI-Setup.exe first; this adds the ' +
      '{#ProgramName} to the same folder.', mbError, MB_OK, IDOK);
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
