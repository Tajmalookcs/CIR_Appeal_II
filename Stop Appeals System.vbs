' ============================================================
'  Commissioner (Appeals-II), Inland Revenue
'
'  Double-click this file to stop the Appeals Management
'  System server. Use it when you are finished for the day,
'  or before taking a backup of the database.
' ============================================================

Option Explicit

Const PORT = 8020

Dim fso, projectDir, wmi, processes, proc, killed, cmdLine

Set fso = CreateObject("Scripting.FileSystemObject")
projectDir = fso.GetParentFolderName(WScript.ScriptFullName)

killed = 0

On Error Resume Next
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
If Err.Number <> 0 Then
    MsgBox "Could not query running programs on this computer.", _
           vbCritical, "Appeals System - Cannot Stop"
    WScript.Quit 1
End If
On Error GoTo 0

' Only stop this project's server - never another Python program.
Set processes = wmi.ExecQuery( _
    "SELECT ProcessId, CommandLine FROM Win32_Process " & _
    "WHERE Name = 'pythonw.exe' OR Name = 'python.exe'")

For Each proc In processes
    cmdLine = "" & proc.CommandLine
    If InStr(1, cmdLine, projectDir, vbTextCompare) > 0 _
       And InStr(1, cmdLine, "runserver", vbTextCompare) > 0 Then
        On Error Resume Next
        proc.Terminate()
        If Err.Number = 0 Then killed = killed + 1
        On Error GoTo 0
    End If
Next

If killed > 0 Then
    MsgBox "Appeals System stopped." & vbCrLf & vbCrLf & _
           killed & " server process(es) closed.", _
           vbInformation, "Appeals System"
Else
    MsgBox "The Appeals System does not appear to be running.", _
           vbInformation, "Appeals System"
End If
