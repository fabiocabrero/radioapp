; Inno Setup: instalador do IC-7300 Station. Compilado por installer/build.py (define SourceDir, AppVersion e OutDir).
#ifndef AppVersion
  #define AppVersion "0.2.0"
#endif

[Setup]
AppId={{6B2F5E1E-7C0A-4B0D-9E75-1C7300A5710A}
AppName=IC-7300 Station
AppVersion={#AppVersion}
AppPublisher=Fabio Cabrero (PR2FAB)
AppPublisherURL=https://github.com/fabiocabrero/radioapp
DefaultDirName={autopf}\IC7300 Station
DefaultGroupName=IC-7300 Station
UninstallDisplayIcon={app}\IC7300Station.exe
OutputDir={#OutDir}
OutputBaseFilename=IC7300Station-Setup-{#AppVersion}
SetupIconFile=ic7300.ico
Compression=lzma2/max
SolidCompression=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na área de trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; DestName: "LEIA-ME.md"; Flags: ignoreversion

[Icons]
Name: "{group}\IC-7300 Station"; Filename: "{app}\IC7300Station.exe"
Name: "{group}\Assistente de primeiros passos"; Filename: "{app}\IC7300Station.exe"
Name: "{group}\Desinstalar IC-7300 Station"; Filename: "{uninstallexe}"
Name: "{autodesktop}\IC-7300 Station"; Filename: "{app}\IC7300Station.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\IC7300Station.exe"; Description: "Abrir o IC-7300 Station (na primeira vez abre o assistente: seus dados, programas de terceiros e instruções)"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Messages]
FinishedLabel=O IC-7300 Station foi instalado.%n%nSuas configurações e o log de contatos ficam em %APPDATA%\IC7300App e são mantidos ao desinstalar.
