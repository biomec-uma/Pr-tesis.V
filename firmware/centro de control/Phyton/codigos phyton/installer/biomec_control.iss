; Instalador de BIOMEC Control (Inno Setup 6). Lo genera release.ps1:
;     ISCC.exe /DAppVersion=0.3.0 installer\biomec_control.iss   ->  dist\BIOMEC-Control-Setup-0.3.0.exe
;
; - Se instala para el usuario (sin permisos de administrador) en %LOCALAPPDATA%\Programs\BIOMEC Control.
; - Acceso en el menú Inicio (y, si se marca, en el escritorio) y desinstalador en Configuración > Aplicaciones.
; - Actualizar = ejecutar el instalador nuevo encima. La app lo hace sola en silencio:
;       BIOMEC-Control-Setup-X.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /relanzar=1
;   El instalador espera a que la app se cierre (mutex BiomecControlApp), la actualiza y la vuelve a abrir.
; - Los datos del usuario (ajustes, posturas, sesiones, modelos, voz) están fuera de {app}: no se tocan.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "BIOMEC Control"
#define AppExe "BIOMEC Control.exe"
#define AppMutex "BiomecControlApp"

[Setup]
; El AppId identifica la app entre versiones: NO cambiarlo nunca (si cambia, se instalaría duplicada).
AppId={{DD06A351-C9AE-4D07-B33E-26459FA1CEA9}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=BIOMEC UMA
AppPublisherURL=https://github.com/biomec-uma/Pr-tesis.V
AppSupportURL=https://github.com/biomec-uma/Pr-tesis.V/issues
AppUpdatesURL=https://github.com/biomec-uma/Pr-tesis.V/releases
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=BIOMEC-Control-Setup-{#AppVersion}
SetupIconFile=..\assets\biomec.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ShowLanguageDialog=no
; la app se cierra sola antes de actualizar (ver [Code]): no hace falta el gestor de reinicio de Windows
CloseApplications=no

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear un acceso directo en el escritorio"; Flags: unchecked

[InstallDelete]
; quita los módulos de la versión anterior para que no se mezclen con los nuevos
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "BiomecUMA.Control"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "BiomecUMA.Control"; Tasks: escritorio

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir {#AppName}"; Flags: nowait postinstall skipifsilent
; actualización desde la app: volver a abrirla al terminar
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: Relanzar

[Code]
function AppAbierta: Boolean;
begin
  Result := CheckForMutexes('{#AppMutex}');
end;

function InitializeSetup: Boolean;
var
  Intentos: Integer;
begin
  Result := True;
  if WizardSilent then
  begin
    { actualización desde la app: esperar (como mucho 30 s) a que termine de cerrarse }
    Intentos := 0;
    while AppAbierta and (Intentos < 120) do
    begin
      Sleep(250);
      Intentos := Intentos + 1;
    end;
  end
  else
  begin
    while AppAbierta do
    begin
      if MsgBox('{#AppName} está abierta. Ciérrala y pulsa Aceptar para continuar.',
                mbInformation, MB_OKCANCEL) = IDCANCEL then
      begin
        Result := False;
        Exit;
      end;
    end;
  end;
end;

function InitializeUninstall: Boolean;
begin
  Result := True;
  while AppAbierta do
  begin
    if MsgBox('{#AppName} está abierta. Ciérrala y pulsa Aceptar para desinstalarla.',
              mbInformation, MB_OKCANCEL) = IDCANCEL then
    begin
      Result := False;
      Exit;
    end;
  end;
end;

function Relanzar: Boolean;
begin
  Result := ExpandConstant('{param:relanzar|0}') = '1';
end;
