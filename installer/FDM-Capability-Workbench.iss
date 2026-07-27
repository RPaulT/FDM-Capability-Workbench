#define MyAppName "FDM-Capability-Workbench"
#define MyAppVersion "1.5.0"
#define MyAppPublisher "Ruben Paul Thomsen"
#define MyAppExeName "FDM-Capability-Workbench.exe"

[Setup]
AppId={{F4A6E17F-1F9E-4BF8-A4D7-2BD16B77C47A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}

DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}

PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

OutputDir=output
OutputBaseFilename=FDM-Capability-Workbench-Setup-1.5.0

Compression=lzma2
SolidCompression=yes
WizardStyle=modern

SetupLogging=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; \
    Description: "Desktopverknüpfung erstellen"; \
    GroupDescription: "Zusätzliche Aufgaben:"; \
    Flags: unchecked

[Files]
Source: "..\dist\FDM-Capability-Workbench\*"; \
    DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\FDM-Capability-Workbench"; \
    Filename: "{app}\{#MyAppExeName}"

Name: "{autodesktop}\FDM-Capability-Workbench"; \
    Filename: "{app}\{#MyAppExeName}"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; \
    Description: "FDM-Capability-Workbench starten"; \
    Flags: nowait postinstall skipifsilent