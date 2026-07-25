!macro customUnInstall
  ; Stop only the backend located inside this installation. Stable and Beta
  ; editions may run side by side and must not terminate each other's backend.
  nsExec::ExecToLog '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "$INSTDIR\resources\uninstall-stop-backend.ps1" -InstallDir "$INSTDIR"'

  ${ifNot} ${isUpdated}
    MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON1 "是否保留 ModAgent 公测版的测试数据？选择“是”将保留公测设置、日志和测试记录；选择“否”将清理公测版数据，不影响正式版。" /SD IDYES IDYES beta_keep_data IDNO beta_remove_data

    beta_remove_data:
      RMDir /r "$PROFILE\.modagent-beta"
      RMDir /r "$APPDATA\ModAgent Beta"
      RMDir /r "$LOCALAPPDATA\ModAgent Beta"
      RMDir /r "$APPDATA\ModAgent P Beta"
      RMDir /r "$LOCALAPPDATA\ModAgent P Beta"
      RMDir /r "$APPDATA\ModAgent Pro Beta"
      RMDir /r "$LOCALAPPDATA\ModAgent Pro Beta"
      Goto beta_cleanup_done

    beta_keep_data:
    beta_cleanup_done:
  ${endIf}
!macroend
