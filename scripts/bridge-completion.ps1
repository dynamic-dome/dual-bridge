# Completion for dual-bridge lane names and bridge commands.
#
# Load for the current PowerShell session with:
#   . .\scripts\bridge-completion.ps1

$global:DualBridgeCompletionWords = @(
    "lane-A-to-B",
    "lane-B-to-A",
    "handoff_write",
    "handoff_poll",
    "handoff_collect",
    "handoff_write.py",
    "handoff_poll.py",
    "handoff_collect.py"
)

function global:Complete-DualBridgeWord {
    param(
        [string]$WordToComplete
    )

    $global:DualBridgeCompletionWords |
        Where-Object { $_ -like "$WordToComplete*" } |
        ForEach-Object {
            [System.Management.Automation.CompletionResult]::new(
                $_,
                $_,
                [System.Management.Automation.CompletionResultType]::ParameterValue,
                $_
            )
        }
}

$script:DualBridgeCompletionCommands = @(
    "handoff_write",
    "handoff_poll",
    "handoff_collect",
    "handoff_write.py",
    "handoff_poll.py",
    "handoff_collect.py"
)

Register-ArgumentCompleter -Native -CommandName $script:DualBridgeCompletionCommands -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)

    Complete-DualBridgeWord -WordToComplete $wordToComplete
}

Register-ArgumentCompleter -Native -CommandName python, py, python.exe, py.exe -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)

    Complete-DualBridgeWord -WordToComplete $wordToComplete
}
