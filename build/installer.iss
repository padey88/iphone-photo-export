; Inno Setup 6 script — single-file installer for iPhone Photo Export.
; Bundled: Python runtime + Flask + pymobiledevice3 + Pillow/pillow-heif,
;          ffmpeg/ffprobe, the web UI, and Apple's USB device driver (MSI).
; Built by build.ps1:  ISCC.exe /DAppVersion=x.y.z /DSourceDir=... installer.iss

#ifndef AppVersion
  #define AppVersion "1.0.0"
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
; Big payload (Python runtime + ffmpeg); avoid a 32-bit limit surprise.
DiskSpanning=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
; --- the frozen app: exe, Python DLLs, all packages, web assets -------------
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; --- Apple Mobile Device Support (usbmuxd) MSI, extracted from iTunes ------
;     Staged to {tmp} and deleted after install: it is only needed once.
Source: "{#SourceDir}\drivers\{#DriverMsi}"; DestDir: "{tmp}\iphotodrv"; \
  Flags: deleteafterinstall; Check: NeedsAppleDriver

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{#AppName} (log)"; Filename: "{app}\{#AppExe}"; Parameters: "--serve"; Comment: "Run without a window (diagnostics)"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; 1) Apple's USB device driver — only when the service is missing.
Filename: "{sys}\msiexec.exe"; \
  Parameters: "/i ""{tmp}\iphotodrv\{#DriverMsi}"" /qn /norestart /l*v ""{log}\apple-driver.log"""; \
  StatusMsg: "Installing Apple USB device driver (one time)..."; \
  Check: NeedsAppleDriver; Flags: waituntilterminated

; 2) Launch the app the first time.
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; \
  Flags: nowait postinstall skipifsilent

[UninstallRun]
; Stop a running instance so the folder can be removed.
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im {#AppExe}"; Flags: runhidden skipifdoesntexist; RunOnceId: "KillApp"

[UninstallDelete]
; Only things the app itself creates inside {app}; user photos are never touched.
Type: filesandordirs; Name: "{app}\cache"
Type: dirifempty; Name: "{app}"

[Code]
const
  SVC = 'Apple Mobile Device Service';

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

procedure InitializeWizard;
var
  P: Integer;
begin
  { A missing WebView2 is not fatal: the app falls back to the default browser. }
  if WebView2Version = '' then
  begin
    P := MsgBox('WebView2 runtime was not detected on this PC.' + #13#10#13#10 +
                'The app will open in your default browser instead of a native window. ' +
                'Install "Microsoft Edge WebView2 Runtime" for the native experience.' + #13#10#13#10 +
                'Continue with the installation?', mbConfirmation, MB_YESNO);
    if P = IDNO then
      Abort;
  end;
end;

function AppleDriverMessage: String;
begin
  if NeedsAppleDriver then
    Result := 'Apple USB device driver (Apple Mobile Device Support) is not installed and will be installed now.'
  else
    Result := 'Apple USB device driver already present - skipping.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    Log(AppleDriverMessage);
end;
