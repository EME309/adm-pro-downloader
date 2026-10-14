' ADM Pro - silent launcher (no console window)
' Runs start.bat hidden. If the app exits with an error, a message box is shown.
Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = fso.GetParentFolderName(WScript.ScriptFullName)

' Tells start.bat there is no visible console, so it must never wait for a key press
WshShell.Environment("Process")("ADM_SILENT") = "1"

rc = WshShell.Run("cmd /c start.bat", 0, True)

If rc <> 0 Then
    MsgBox "ADM Pro stopped with an error (code " & rc & ")." & vbCrLf & vbCrLf & _
           "Details are saved in the logs folder next to the app (app.log, setup.log).", 48, "ADM Pro"
End If

Set WshShell = Nothing
Set fso = Nothing