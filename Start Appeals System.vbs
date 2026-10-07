' ============================================================
'  Commissioner (Appeals-II), Inland Revenue
'  Building Regional Tax Office, Faisalabad
'
'  Double-click this file to start the Appeals Management
'  System. The server runs hidden (no black window) and the
'  browser opens automatically.
' ============================================================

Option Explicit

Const PORT = 8020
Const APP_HOST = "127.0.0.1"
Const OPEN_BROWSER = True     ' set to False to start the server only
Const WAIT_SECONDS = 30

Dim fso, shell, projectDir, batFile, pythonExe, managePy, appUrl
Dim logDir, logFile, waited

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

projectDir = fso.GetParentFolderName(WScript.ScriptFullName)
batFile    = projectDir & "\run_server.bat"
pythonExe  = projectDir & "\venv\Scripts\python.exe"
managePy   = projectDir & "\manage.py"
logDir     = projectDir & "\logs"
logFile    = logDir & "\server.log"

' Port 80 is the browser default, so it would be left out of the address.
If PORT = 80 Then
    appUrl = "http://" & APP_HOST & "/"
Else
    appUrl = "http://" & APP_HOST & ":" & PORT & "/"
End If

' ---- sanity checks -----------------------------------------
If Not fso.FileExists(pythonExe) Then
    Fail "Python was not found at:" & vbCrLf & vbCrLf & pythonExe & vbCrLf & vbCrLf & _
         "The 'venv' folder appears to be missing or moved."
End If

If Not fso.FileExists(managePy) Then
    Fail "manage.py was not found at:" & vbCrLf & vbCrLf & managePy & vbCrLf & vbCrLf & _
         "Keep this file inside the project folder."
End If

If Not fso.FileExists(batFile) Then
    Fail "run_server.bat is missing from:" & vbCrLf & vbCrLf & projectDir
End If

' ---- already running? just open the browser ----------------
If ServerProcessCount(projectDir) > 0 Then
    If OPEN_BROWSER Then shell.Run appUrl, 1, False
    WScript.Quit 0
End If

' ---- start the server, completely hidden -------------------
' Window style 0 hides the console, so no black window appears.
' python.exe is used rather than pythonw.exe: under pythonw the
' standard output does not exist and Django's runserver exits the
' moment it tries to print its startup banner.
If Not fso.FolderExists(logDir) Then fso.CreateFolder logDir

shell.CurrentDirectory = projectDir
shell.Run """" & batFile & """ " & PORT, 0, False

' ---- wait until the server is actually listening ------------
waited = 0
Do While waited < WAIT_SECONDS * 2
    WScript.Sleep 500
    If PortIsListening(PORT) Then
        If OPEN_BROWSER Then shell.Run appUrl, 1, False
        WScript.Quit 0
    End If
    waited = waited + 1
Loop

Fail "The Appeals System did not start within " & WAIT_SECONDS & " seconds." & vbCrLf & vbCrLf & _
     "The reason is usually recorded at the end of:" & vbCrLf & logFile


' ============================================================
'  True once something is listening on the given local port.
'  Uses netstat via a hidden command, so no proxy settings and
'  no firewall prompts are involved.
' ============================================================
Function PortIsListening(portNumber)
    Dim exec, output, lines, i, line, target

    PortIsListening = False
    target = "127.0.0.1:" & portNumber

    On Error Resume Next
    Set exec = shell.Exec("netstat -an -p TCP")
    If Err.Number <> 0 Then Exit Function
    output = exec.StdOut.ReadAll()
    If Err.Number <> 0 Then Exit Function
    On Error GoTo 0

    ' Check line by line and require the address to be followed by whitespace.
    ' A plain InStr would match 127.0.0.1:8020 when looking for 127.0.0.1:80.
    ' The server binds 0.0.0.0 for LAN access, so accept either form.
    lines = Split(output, vbCrLf)
    For i = 0 To UBound(lines)
        line = Trim(Replace(lines(i), vbTab, " ")) & " "
        If InStr(1, line, "LISTENING", vbTextCompare) > 0 Then
            If InStr(1, line, "0.0.0.0:" & portNumber & " ", vbTextCompare) > 0 _
               Or InStr(1, line, target & " ", vbTextCompare) > 0 Then
                PortIsListening = True
                Exit Function
            End If
        End If
    Next
End Function


' ============================================================
'  How many Python servers are already running for this folder.
' ============================================================
Function ServerProcessCount(folder)
    Dim wmi, list, proc, cmdLine, total
    total = 0
    On Error Resume Next
    Set wmi = GetObject("winmgmts:\\.\root\cimv2")
    If Err.Number <> 0 Then
        ServerProcessCount = 0
        Exit Function
    End If
    Set list = wmi.ExecQuery( _
        "SELECT ProcessId, CommandLine FROM Win32_Process WHERE Name = 'python.exe'")
    For Each proc In list
        cmdLine = "" & proc.CommandLine
        If InStr(1, cmdLine, folder, vbTextCompare) > 0 _
           And InStr(1, cmdLine, "runserver", vbTextCompare) > 0 Then
            total = total + 1
        End If
    Next
    On Error GoTo 0
    ServerProcessCount = total
End Function


Sub Fail(message)
    MsgBox message, vbExclamation, "Appeals System - Cannot Start"
    WScript.Quit 1
End Sub
