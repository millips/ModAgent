Unicode true
RequestExecutionLevel user
ManifestDPIAware true

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "Sections.nsh"
!include "nsDialogs.nsh"

!ifndef PRODUCT_VERSION
  !define PRODUCT_VERSION "1.10.0"
!endif
!ifndef OUTPUT_FILE
  !define OUTPUT_FILE "ModAgent-Cleanup.exe"
!endif

Name "ModAgent 一键清理器"
OutFile "${OUTPUT_FILE}"
InstallDir "$TEMP"
ShowInstDetails show
BrandingText "ModAgent Cleanup ${PRODUCT_VERSION}"
VIProductVersion "${PRODUCT_VERSION}.0"
VIAddVersionKey "ProductName" "ModAgent 一键清理器"
VIAddVersionKey "FileDescription" "Remove ModAgent programs and selected user data"
VIAddVersionKey "FileVersion" "${PRODUCT_VERSION}"

!define MUI_ABORTWARNING
!define MUI_COMPONENTSPAGE_SMALLDESC
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
Page custom CustomPageCreate CustomPageLeave
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_LANGUAGE "SimpChinese"

Var DryRun
Var LogHandle
Var CustomCheckbox
Var CustomInput
Var CustomBrowseButton
Var CustomEnabled
Var CustomPath

!macro LogTarget kind target
  ${If} $DryRun == "1"
    FileWrite $LogHandle "${kind}$\t${target}$\r$\n"
  ${EndIf}
!macroend

!macro RemoveDir target
  !insertmacro LogTarget "DIR" "${target}"
  ${If} $DryRun != "1"
    RMDir /r "${target}"
  ${EndIf}
!macroend

!macro RemoveFile target
  !insertmacro LogTarget "FILE" "${target}"
  ${If} $DryRun != "1"
    Delete "${target}"
  ${EndIf}
!macroend

!macro RemoveReg key
  !insertmacro LogTarget "REG" "HKCU\${key}"
  ${If} $DryRun != "1"
    DeleteRegKey HKCU "${key}"
  ${EndIf}
!macroend

Function CustomPageCreate
  IfSilent skip
  nsDialogs::Create 1018
  Pop $R0
  ${If} $R0 == error
    Abort
  ${EndIf}

  ${NSD_CreateLabel} 0 0 100% 26u "如果你使用的是手动解压版，可额外选择其根目录。只有检测到 ModAgent 主程序和 resources\app.asar 时才允许删除。"
  Pop $R0
  ${NSD_CreateCheckbox} 0 34u 100% 12u "同时清理一个手动解压的 ModAgent 目录"
  Pop $CustomCheckbox
  ${NSD_CreateDirRequest} 0 54u 78% 13u ""
  Pop $CustomInput
  ${NSD_CreateBrowseButton} 80% 53u 20% 15u "浏览..."
  Pop $CustomBrowseButton
  ${NSD_OnClick} $CustomBrowseButton CustomBrowse
  nsDialogs::Show
skip:
FunctionEnd

Function CustomBrowse
  nsDialogs::SelectFolderDialog "选择手动解压的 ModAgent 根目录" ""
  Pop $R0
  ${If} $R0 != error
    ${NSD_SetText} $CustomInput $R0
  ${EndIf}
FunctionEnd

Function CustomPageLeave
  ${NSD_GetState} $CustomCheckbox $R0
  ${If} $R0 != ${BST_CHECKED}
    StrCpy $CustomEnabled "0"
    Return
  ${EndIf}
  ${NSD_GetText} $CustomInput $CustomPath
  GetFullPathName $CustomPath "$CustomPath"
  ${If} $CustomPath == ""
    MessageBox MB_ICONSTOP "请选择手动解压目录。"
    Abort
  ${EndIf}
  ${If} $CustomPath == $EXEDIR
    MessageBox MB_ICONSTOP "请先把清理器移到 ModAgent 目录之外，再选择该目录。"
    Abort
  ${EndIf}
  ${If} $CustomPath == $PROFILE
  ${OrIf} $CustomPath == $LOCALAPPDATA
  ${OrIf} $CustomPath == $APPDATA
  ${OrIf} $CustomPath == $PROGRAMFILES
  ${OrIf} $CustomPath == $WINDIR
    MessageBox MB_ICONSTOP "拒绝清理过于宽泛的系统或用户目录。"
    Abort
  ${EndIf}
  IfFileExists "$CustomPath\resources\app.asar" marker_ok marker_bad
marker_ok:
  IfFileExists "$CustomPath\ModAgent.exe" valid
  IfFileExists "$CustomPath\ModAgentPro.exe" valid
  IfFileExists "$CustomPath\ModAgentProBeta.exe" valid marker_bad
marker_bad:
  MessageBox MB_ICONSTOP "所选目录未同时包含 ModAgent 主程序和 resources\app.asar，已拒绝删除。"
  Abort
valid:
  StrCpy $CustomEnabled "1"
FunctionEnd

Section "ModAgent 程序、快捷方式和注册信息（必选）" SEC_PROGRAM
  SectionIn RO
  ${If} $DryRun == "1"
    FileOpen $LogHandle "$TEMP\ModAgent-Cleanup-dry-run.txt" w
    FileWrite $LogHandle "ModAgent Cleanup ${PRODUCT_VERSION}$\r$\n"
  ${Else}
    nsExec::ExecToLog '"$SYSDIR\taskkill.exe" /F /IM ModAgent.exe'
    nsExec::ExecToLog '"$SYSDIR\taskkill.exe" /F /IM ModAgentPro.exe'
    nsExec::ExecToLog '"$SYSDIR\taskkill.exe" /F /IM ModAgentProBeta.exe'
    nsExec::ExecToLog '"$SYSDIR\taskkill.exe" /F /IM ModAgentBackend.exe'
  ${EndIf}

  !insertmacro RemoveDir "$LOCALAPPDATA\Programs\ModAgent"
  !insertmacro RemoveDir "$LOCALAPPDATA\Programs\ModAgent Pro"
  !insertmacro RemoveDir "$LOCALAPPDATA\Programs\ModAgent Pro Beta"
  !insertmacro RemoveFile "$DESKTOP\ModAgent.lnk"
  !insertmacro RemoveFile "$DESKTOP\ModAgent Pro.lnk"
  !insertmacro RemoveFile "$DESKTOP\ModAgent Pro Beta.lnk"
  !insertmacro RemoveDir "$SMPROGRAMS\ModAgent"
  !insertmacro RemoveDir "$SMPROGRAMS\ModAgent Pro"
  !insertmacro RemoveDir "$SMPROGRAMS\ModAgent Pro Beta"
  !insertmacro RemoveReg "Software\Microsoft\Windows\CurrentVersion\Uninstall\com.modagent.desktop"
  !insertmacro RemoveReg "Software\Microsoft\Windows\CurrentVersion\Uninstall\com.modagent.desktop.pro"
  !insertmacro RemoveReg "Software\Microsoft\Windows\CurrentVersion\Uninstall\com.modagent.desktop.pro.beta"
SectionEnd

Section "清除公测版数据（.modagent-beta）" SEC_BETA_DATA
  !insertmacro RemoveDir "$PROFILE\.modagent-beta"
  !insertmacro RemoveDir "$APPDATA\ModAgent Beta"
  !insertmacro RemoveDir "$LOCALAPPDATA\ModAgent Beta"
  !insertmacro RemoveDir "$APPDATA\ModAgent Pro Beta"
  !insertmacro RemoveDir "$LOCALAPPDATA\ModAgent Pro Beta"
SectionEnd

Section /o "清除稳定版数据（.modagent，可选且不可恢复）" SEC_STABLE_DATA
  !insertmacro RemoveDir "$PROFILE\.modagent"
  !insertmacro RemoveDir "$APPDATA\ModAgent"
  !insertmacro RemoveDir "$APPDATA\ModAgent Pro"
  !insertmacro RemoveDir "$LOCALAPPDATA\ModAgent"
  !insertmacro RemoveDir "$LOCALAPPDATA\ModAgent Pro"
SectionEnd

Section "清理已选择的手动解压目录" SEC_CUSTOM
  SectionIn RO
  ${If} $CustomEnabled == "1"
    !insertmacro RemoveDir "$CustomPath"
  ${EndIf}
SectionEnd

Section -Finish
  ${If} $DryRun == "1"
    FileClose $LogHandle
    SetDetailsPrint both
    DetailPrint "DRY RUN：未删除任何内容。计划已写入 $TEMP\ModAgent-Cleanup-dry-run.txt"
  ${Else}
    SetDetailsPrint both
    DetailPrint "清理完成。未勾选的数据已保留。"
  ${EndIf}
SectionEnd

Function .onInit
  StrCpy $DryRun "0"
  StrCpy $CustomEnabled "0"
  StrCpy $CustomPath ""
  ${GetParameters} $R0

  ClearErrors
  ${GetOptions} $R0 "/DRYRUN=" $R1
  ${IfNot} ${Errors}
    StrCpy $DryRun $R1
  ${EndIf}

  ClearErrors
  ${GetOptions} $R0 "/PURGE_STABLE=" $R1
  ${IfNot} ${Errors}
    ${If} $R1 == "1"
      !insertmacro SelectSection ${SEC_STABLE_DATA}
    ${EndIf}
  ${EndIf}

  IfSilent done
  MessageBox MB_ICONEXCLAMATION|MB_OKCANCEL "此工具会关闭 ModAgent，并永久删除所选程序与数据。$\r$\n$\r$\n.modagent 稳定版数据默认不勾选，只有你明确选择后才会删除。$\r$\n删除后无法恢复。" IDOK done
  Abort
done:
FunctionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_PROGRAM} "关闭 ModAgent，清除标准安装目录、快捷方式和当前用户注册信息。"
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_BETA_DATA} "删除公测版配置、数据库、日志、浏览器配置与下载缓存。"
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_STABLE_DATA} "删除稳定版 .modagent 数据；默认不选，删除后不可恢复。"
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_CUSTOM} "仅清除上一页通过双重文件标记验证的手动解压目录。"
!insertmacro MUI_FUNCTION_DESCRIPTION_END
