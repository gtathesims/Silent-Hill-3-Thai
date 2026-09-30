; Silent Hill 3 Thai localization installer UI.
; Inno Setup owns the wizard and file placement. ModPatcher.exe owns all
; detection, backup, patch, validation, rollback, logging, and restore logic.

#define AppName "Silent Hill 3 ภาษาไทย"
#define AppVersion "1.4.1"
#define AppFolderName "SilentHill3ThaiMod"
#define GameName "Silent Hill 3"
#define GameExeName "sh3.exe"
#define TargetFileName "data\msg.arc"
#define PatcherName "ModPatcher.exe"
#define BackupFolderName ".thai_mod_installer"
#define BundleDir "..\build\windows_bundle\SilentHill3ThaiModInstaller"

[Setup]
AppId={{2D03863A-4010-4A9A-B1D7-BF1C0BE4BB26}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\{#AppFolderName}
DisableWelcomePage=no
DisableDirPage=yes
DisableReadyPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
Uninstallable=no
Compression=zip
SolidCompression=no
WizardStyle=modern
WizardImageFile=assets\welcome.bmp
OutputDir=..\release
OutputBaseFilename=SilentHill3ThaiModSetup_v1.4.1

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; The standalone engine embeds only the mod payload and adapters it requires.
; Includes the verified original executable for the compatibility fallback.
Source: "{#BundleDir}\{#PatcherName}"; DestDir: "{app}"; Flags: ignoreversion

[Code]
var
  GameDirPage: TInputDirWizardPage;
  ActionPage: TInputOptionWizardPage;
  OperationSucceeded: Boolean;

function StateDir: String;
begin
  Result := AddBackslash(GameDirPage.Values[0]) + '{#BackupFolderName}';
end;

function IsRestore: Boolean;
begin
  Result := ActionPage.SelectedValueIndex = 1;
end;

function IsValidGameFolder(const Dir: String): Boolean;
begin
  Result :=
    DirExists(Dir) and
    FileExists(AddBackslash(Dir) + '{#GameExeName}') and
    FileExists(AddBackslash(Dir) + '{#TargetFileName}');
end;

function RunEngine(const Mode: String): Boolean;
var
  ResultCode: Integer;
  Params: String;
begin
  Params :=
    '--game-dir "' + RemoveBackslashUnlessRoot(GameDirPage.Values[0]) + '" ' +
    '--state-dir "' + StateDir + '" ' + Mode;
  Result := Exec(
    ExpandConstant('{app}\{#PatcherName}'),
    Params,
    ExpandConstant('{app}'),
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode) and (ResultCode = 0);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = GameDirPage.ID then begin
    if not IsValidGameFolder(GameDirPage.Values[0]) then begin
      MsgBox(
        'ไม่พบไฟล์เกมที่รองรับ กรุณาเลือกโฟลเดอร์หลักของ {#GameName}' + #13#10 +
        'โฟลเดอร์ที่ถูกต้องต้องมี {#GameExeName} และ {#TargetFileName}',
        mbError,
        MB_OK);
      Result := False;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Ok: Boolean;
begin
  if CurStep <> ssPostInstall then begin
    exit;
  end;

  if IsRestore then begin
    WizardForm.StatusLabel.Caption := 'กำลังตรวจ backup และคืนไฟล์เกมเดิม…';
    Ok := RunEngine('--restore');
  end else begin
    WizardForm.StatusLabel.Caption := 'กำลังตรวจความเข้ากันได้ของเกม…';
    Ok := RunEngine('--dry-run --allow-exe-fallback');
    if Ok then begin
      WizardForm.StatusLabel.Caption := 'กำลังสำรอง แพตช์ และตรวจสอบไฟล์เกม…';
      Ok := RunEngine('--patch --allow-exe-fallback');
    end;
  end;

  OperationSucceeded := Ok;
  if not Ok then begin
    RaiseException(
      'ดำเนินการไม่สำเร็จ Patch engine ได้หยุดอย่างปลอดภัย และเกมไม่ได้ถูกปล่อยไว้ในสถานะแพตช์ครึ่งเดียว');
  end;
end;

procedure InitializeWizard;
begin
  OperationSucceeded := False;

  WizardForm.WelcomeLabel1.Caption :=
    '{#AppName} สำหรับ {#GameName}';
  WizardForm.WelcomeLabel2.Caption :=
    'ตัวติดตั้งข้อความ ฟอนต์ และภาพเมนูภาษาไทย' + #13#10 + #13#10 +
    'หมายเหตุ:' + #13#10 +
    '- แปลโดยใช้ AI' + #13#10 +
    '- อาจมีบางประโยคที่ยังเป็นภาษาอังกฤษและแสดงภาษาไทยไม่ครบ' + #13#10 +
    '- แจกฟรีเท่านั้น ห้ามนำไปจำหน่าย';

  GameDirPage := CreateInputDirPage(
    wpWelcome,
    'เลือกโฟลเดอร์เกม {#GameName}',
    'เลือกโฟลเดอร์ที่มี {#GameExeName}',
    'ช่องนี้ต้องเป็นโฟลเดอร์หลักของเกมโดยตรง',
    False,
    '');
  GameDirPage.Add('Game Folder:');

  ActionPage := CreateInputOptionPage(
    GameDirPage.ID,
    'เลือกการทำงาน',
    'ติดตั้งหรือถอนม็อด',
    '',
    True,
    False);
  ActionPage.Add('ติดตั้งม็อดภาษาไทย');
  ActionPage.Add('ถอนม็อดและคืนไฟล์เดิม');
  ActionPage.SelectedValueIndex := 0;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then begin
    WizardForm.FinishedHeadingLabel.Caption :=
      'ติดตั้ง/ถอนการติดตั้ง เสร็จสมบูรณ์';
    if OperationSucceeded then begin
      if IsRestore then begin
        WizardForm.FinishedLabel.Caption :=
          'คืนไฟล์เกมเดิมและตรวจสอบ hash เรียบร้อยแล้ว' + #13#10 + #13#10 +
          'คลิก Finish เพื่อออกจากโปรแกรม';
      end else begin
        WizardForm.FinishedLabel.Caption :=
          'ติดตั้งภาษาไทยและตรวจสอบผลลัพธ์เรียบร้อยแล้ว' + #13#10 + #13#10 +
          'คลิก Finish เพื่อออกจากโปรแกรม';
      end;
    end;
  end;
end;
