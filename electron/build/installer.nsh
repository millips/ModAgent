!macro customUnInstall
  ; Stop the packaged backend before electron-builder removes $INSTDIR. A
  ; force-closed desktop process may otherwise leave this child process alive.
  nsExec::ExecToLog '"$SYSDIR\taskkill.exe" /F /IM ModAgentBackend.exe'
  Sleep 800

  ${ifNot} ${isUpdated}
    MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON1 "是否保留 ModAgent 的全部本地数据？选择“是”将保留业务数据、设置和缓存；选择“否”将继续选择清理范围。" /SD IDYES IDYES uninstall_keep_all IDNO uninstall_choose_cleanup

    uninstall_choose_cleanup:
    MessageBox MB_YESNO|MB_ICONEXCLAMATION|MB_DEFBUTTON2 "是否完全清除共享业务数据？选择“是”将删除 .modagent（包括快照、会话、Mod 清单和加密密钥）以及应用缓存；选择“否”将仅删除应用缓存和界面设置。" /SD IDNO IDYES uninstall_remove_all IDNO uninstall_remove_appdata

    uninstall_remove_all:
      RMDir /r "$PROFILE\.modagent"
      RMDir /r "$APPDATA\ModAgent"
      RMDir /r "$LOCALAPPDATA\ModAgent"
      RMDir /r "$APPDATA\ModAgent Pro"
      RMDir /r "$LOCALAPPDATA\ModAgent Pro"
      Goto uninstall_cleanup_done

    uninstall_remove_appdata:
      RMDir /r "$APPDATA\ModAgent"
      RMDir /r "$LOCALAPPDATA\ModAgent"
      RMDir /r "$APPDATA\ModAgent Pro"
      RMDir /r "$LOCALAPPDATA\ModAgent Pro"
      Goto uninstall_cleanup_done

    uninstall_keep_all:
    uninstall_cleanup_done:
  ${endIf}
!macroend
