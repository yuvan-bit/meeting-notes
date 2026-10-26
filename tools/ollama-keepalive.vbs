Option Explicit

Dim shell, wmi, procs, app
Set shell = CreateObject("WScript.Shell")
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set procs = wmi.ExecQuery("SELECT ProcessId FROM Win32_Process WHERE Name='ollama.exe' OR Name='ollama app.exe'")

If procs.Count = 0 Then
    app = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Ollama\ollama app.exe"
    On Error Resume Next
    shell.Run """" & app & """", 0, False
    On Error GoTo 0
End If
