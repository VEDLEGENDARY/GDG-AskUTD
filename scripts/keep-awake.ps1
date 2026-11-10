param([ValidateRange(1,120)][int]$Minutes = 30)
# Scoped idle-sleep request. Closing the lid or explicit sleep still takes precedence.
Add-Type @"
using System.Runtime.InteropServices;
public static class AskUtdAwake {
 [DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint flags);
}
"@
try {
    if ([AskUtdAwake]::SetThreadExecutionState([uint32]2147483649) -eq 0) { throw 'Idle sleep request failed.' }
    Write-Output "Idle sleep inhibited for at most $Minutes minutes. Ctrl+C restores normal behavior."
    $until = (Get-Date).AddMinutes($Minutes)
    while ((Get-Date) -lt $until) { Start-Sleep -Seconds 5 }
} finally { [void][AskUtdAwake]::SetThreadExecutionState([uint32]2147483648) }
