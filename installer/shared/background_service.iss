{ The Windows service of the VethuQ background service, shared by the installers that stop or remove
  it (the background service's and the command line's). #included in [Code]. Setup never creates the
  service; `vethuq background install` does. }
const
  ServiceName = 'VethuQBackground';

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

{ Stops the service, waits for it to stop and removes it, so its program (vethuqbs.exe, which it holds
  open) can be deleted. Does nothing when the service isn't installed. }
procedure RemoveService;
begin
  if ServiceInstalled then
  begin
    RunSc('stop ' + ServiceName);
    WaitUntilStopped;
    RunSc('delete ' + ServiceName);
  end;
end;
