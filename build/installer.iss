; Inno Setup 6 script — single-file installer for iPhone Photo Export.
; Bundled: Python runtime + Flask + pymobiledevice3 + Pillow/pillow-heif,
;          ffmpeg, the web UI, and Apple's USB device driver (MSI).
; Built by build.ps1:  ISCC.exe /DAppVersion=x.y.z /DSourceDir=... installer.iss

#ifndef AppVersion
  #define AppVersion "1.0.1"
#endif
#ifndef SourceDir
  #define SourceDir "..\payload\iPhonePhotoExport"
#endif

#define AppName        "iPhone Photo Export"
#define AppExe         "iPhonePhotoExport.exe"
#define AppPublisher   "padey88"
#define AppURL         "https://github.com/padey88/iphone-photo-export"
#define DriverMsi      "AppleMobileDeviceSupport64.msi"

[Setup]
AppId={{8E2C41B5-9C3F-4C27-9D8A-1F5B7C2D4E60}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
DefaultDirName={autopf}\iPhone Photo Export
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExe}
OutputBaseFilename=iPhonePhotoExport-{#AppVersion}-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Apple's driver MSI needs elevation, so the whole install runs elevated.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
DiskSpanning=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
; --- the frozen app: exe, Python DLLs, all packages, web assets -------------
; drivers\ is excluded: the MSI belongs in {tmp} only, not in the install dir.
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "\drivers\*"; \
  Flags: ignoreversion recursesubdirs createallsubdirs

; --- Apple Mobile Device Support (usbmuxd host driver), from Apple's iTunes -
;     Staged to {tmp} and deleted after install: it is only needed once.
Source: "{#SourceDir}\drivers\{#DriverMsi}"; DestDir: "{tmp}\iphotodrv"; \
  Flags: deleteafterinstall; Check: NeedsAppleDriver

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{#AppName} (background server)"; Filename: "{app}\{#AppExe}"; \
  Parameters: "--serve"; Comment: "Run without a window (diagnostics)"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; Launch the app the first time (interactive installs only).
Filename: "{app}\{#AppExe}"; \
  Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; \
  Flags: nowait postinstall skipifsilent

[UninstallRun]
; Stop a running instance so the folder can be removed.
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im {#AppExe}"; \
  Flags: runhidden skipifdoesntexist; RunOnceId: "KillApp"

[UninstallDelete]
; Only things the app itself creates inside {app}; user photos are never touched.
Type: filesandordirs; Name: "{app}\cache"
Type: dirifempty; Name: "{app}"

[Code]
const
  SVC = 'Apple Mobile Device Service';

var
  DriverAttempted: Boolean;
  DriverExitCode: Integer;

{ Is Apple's device service (usbmuxd host) already installed? }
function NeedsAppleDriver: Boolean;
var
  S: String;
begin
  Result := True;
  if RegQueryStringValue(HKLM64, 'SYSTEM\CurrentControlSet\Services\' + SVC, 'ImagePath', S) then
    Result := False
  else if RegQueryStringValue(HKLM32, 'SYSTEM\CurrentControlSet\Services\' + SVC, 'ImagePath', S) then
    Result := False;
end;

function WebView2Version: String;
begin
  Result := '';
  if not RegQueryStringValue(HKLM32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Result) then
    if not RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Result) then
      Result := '';
end;

{ Install Apple's driver from code, not [Run], so a failure cannot abort the
  install. A missing driver is survivable (the user can install iTunes later and
  the app still launches); a half-finished setup is not. }
procedure InstallAppleDriver;
var
  Msi, MsiLog, Params: String;
  ResultCode: Integer;
begin
  if not NeedsAppleDriver then
  begin
    Log('Apple driver: already present, skipping');
    Exit;
  end;

  Msi := ExpandConstant('{tmp}\iphotodrv\{#DriverMsi}');
  if not FileExists(Msi) then
  begin
    Log('Apple driver: MSI not staged (' + Msi + '), skipping');
    Exit;
  end;

  // Log next to the MSI: the {log} constant is empty under /VERYSILENT, and
  // msiexec then fails with 1622 ("error opening installation log file").
  MsiLog := ExpandConstant('{tmp}\iphotodrv\apple-driver.log');
  Params := '/i "' + Msi + '" /qn /norestart /l*v "' + MsiLog + '"';
  DriverAttempted := True;
  Log('Apple driver: msiexec ' + Params);

  if not Exec(ExpandConstant('{sys}\msiexec.exe'), Params, '', SW_HIDE,
              ewWaitUntilTerminated, ResultCode) then
  begin
    DriverExitCode := -1;
    Log('Apple driver: could not start msiexec');
  end
  else
  begin
    DriverExitCode := ResultCode;
    Log('Apple driver: exit code ' + IntToStr(ResultCode));
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    InstallAppleDriver;
    // recursesubdirs creates an empty {app}\drivers even though the MSI is
    // excluded from {app}; leave no empty folder behind.
    RemoveDir(ExpandConstant('{app}\drivers'));
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  { The driver runs during ssPostInstall; warn on the final page if it failed.
    3010 = ERROR_SUCCESS_REBOOT_REQUIRED, which is a success for our purposes. }
  if (CurPageID = wpFinished) and DriverAttempted
     and (DriverExitCode <> 0) and (DriverExitCode <> 3010) then
    MsgBox('The app installed, but Apple''s USB device driver did not (code '
           + IntToStr(DriverExitCode) + ').' + #13#10#13#10 +
           'Windows will not see the iPhone until a driver is present. Install ' +
           'iTunes or the "Apple Devices" app from the Microsoft Store, then ' +
           'start this app again.' + #13#10#13#10 +
           'Driver log: ' + ExpandConstant('{tmp}\iphotodrv\apple-driver.log'),
           mbInformation, MB_OK);
end;

procedure InitializeWizard;
begin
  { A missing WebView2 is not fatal: the app falls back to the default browser. }
  if WebView2Version = '' then
    Log('WebView2 not detected; the app will open in the default browser');
end;
