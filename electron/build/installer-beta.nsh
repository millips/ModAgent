!macro customUnInstall
  ${ifNot} ${isUpdated}
    MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON1 "是否保留 ModAgent 公测版的测试数据？选择‘是’将保留公测设置、日志和测试记录；选择‘否’将仅清理公测版数据，不影响正式版。" IDYES beta_keep_data IDNO beta_remove_data

    beta_remove_data:
      RMDir /r "$PROFILE\.modagent-beta"
      RMDir /r "$APPDATA\ModAgent Beta"
      RMDir /r "$APPDATA\ModAgent Pro Beta"
      Goto beta_cleanup_done

    beta_keep_data:
    beta_cleanup_done:
  ${endIf}
!macroend
