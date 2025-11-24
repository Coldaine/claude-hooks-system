<#
.SYNOPSIS
    Test framework for validating Git hooks functionality
.DESCRIPTION
    Tests PowerShell hook scripts to ensure they work correctly with Claude Code
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$HooksDir = "hooks",
    
    [Parameter(Mandatory=$false)]
    [switch]$VerboseOutput,
    
    [Parameter(Mandatory=$false)]
    [switch]$IntegrationTest,
    
    [Parameter(Mandatory=$false)]
    [string]$ChromaEndpoint = "http://localhost:9000"
)

# Color output
$Colors = @{
    Pass = "Green"
    Fail = "Red"
    Info = "Cyan"
    Warning = "Yellow"
    Debug = "Gray"
}

$TestResults = @{
    Total = 0
    Passed = 0
    Failed = 0
    Details = @()
}

function Write-TestResult {
    param(
        [string]$TestName,
        [bool]$Passed,
        [string]$Message = ""
    )
    
    $TestResults.Total++
    $status = if ($Passed) { "PASS" } else { "FAIL" }
    $color = if ($Passed) { $Colors.Pass } else { $Colors.Fail }
    
    Write-Host "[$status] $TestName" -ForegroundColor $color
    if ($Message) {
        Write-Host "       $Message" -ForegroundColor $Colors.Debug
    }
    
    if ($Passed) {
        $TestResults.Passed++
    } else {
        $TestResults.Failed++
    }
    
    $TestResults.Details += @{
        TestName = $TestName
        Passed = $Passed
        Message = $Message
    }
}

function Test-PowerShellSyntax {
    param([string]$ScriptPath)
    
    $testName = "PowerShell Syntax: $(Split-Path $ScriptPath -Leaf)"
    
    try {
        $result = & pwsh -Command "Set-StrictMode -Version Latest; . '$ScriptPath'; exit 0" 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-TestResult -TestName $testName -Passed $true
            return $true
        } else {
            Write-TestResult -TestName $testName -Passed $false -Message "Syntax errors found: $result"
            return $false
        }
    } catch {
        Write-TestResult -TestName $testName -Passed $false -Message "Exception: $_"
        return $false
    }
}

function Test-JsonInputHandling {
    param([string]$ScriptPath)
    
    $testName = "JSON Input Handling: $(Split-Path $ScriptPath -Leaf)"
    
    # Test with valid JSON
    $validJson = @{
        hook_event_name = "UserPromptSubmit"
        session_id = "test-session-123"
        tool_name = "mcp_test_tool"
        cwd = "e:/test/repo"
        prompt = "Test prompt"
    } | ConvertTo-Json -Depth 10 -Compress
    
    try {
        $result = $validJson | & pwsh -File $ScriptPath 2>&1
        # Script should exit with code 0
        if ($LASTEXITCODE -eq 0) {
            Write-TestResult -TestName $testName -Passed $true
            return $true
        } else {
            Write-TestResult -TestName $testName -Passed $false -Message "Script exited with code $LASTEXITCODE"
            return $false
        }
    } catch {
        Write-TestResult -TestName $testName -Passed $false -Message "Exception: $_"
        return $false
    }
}

function Test-InvalidJsonHandling {
    param([string]$ScriptPath)
    
    $testName = "Invalid JSON Handling: $(Split-Path $ScriptPath -Leaf)"
    
    # Test with invalid JSON
    $invalidJson = "{ invalid json }"
    
    try {
        $result = $invalidJson | & pwsh -File $ScriptPath 2>&1
        # Script should handle invalid JSON gracefully (exit 0 or 1 depending on script)
        if ($LASTEXITCODE -in @(0, 1)) {
            Write-TestResult -TestName $testName -Passed $true
            return $true
        } else {
            Write-TestResult -TestName $testName -Passed $false -Message "Unexpected exit code: $LASTEXITCODE"
            return $false
        }
    } catch {
        Write-TestResult -TestName $testName -Passed $false -Message "Exception: $_"
        return $false
    }
}

function Test-McpFiltering {
    param([string]$ScriptPath)
    
    $testName = "MCP Tool Filtering: $(Split-Path $ScriptPath -Leaf)"
    
    # Test with non-MCP tool (should exit 0 with no output)
    $nonMcpJson = @{
        hook_event_name = "PostToolUse"
        session_id = "test-session-123"
        tool_name = "regular_tool"
        cwd = "e:/test/repo"
    } | ConvertTo-Json -Depth 10 -Compress
    
    try {
        $output = $nonMcpJson | & pwsh -File $ScriptPath 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-TestResult -TestName $testName -Passed $true
            return $true
        } else {
            Write-TestResult -TestName $testName -Passed $false -Message "Non-MCP tool caused non-zero exit: $LASTEXITCODE"
            return $false
        }
    } catch {
        Write-TestResult -TestName $testName -Passed $false -Message "Exception: $_"
        return $false
    }
}

function Test-EventLogging {
    param([string]$ScriptPath)
    
    $testName = "Event Logging: $(Split-Path $ScriptPath -Leaf)"
    
    # Set up test log directory
    $testLogDir = "$env:TEMP\claude-hooks-test-$([Guid]::NewGuid())"
    $env:ZO_EVENT_LOG_DIR = $testLogDir
    
    $testJson = @{
        hook_event_name = "UserPromptSubmit"
        session_id = "test-session-123"
        tool_name = "mcp_test_tool"
        cwd = "e:/test/repo"
        prompt = "Test prompt for logging"
    } | ConvertTo-Json -Depth 10 -Compress
    
    try {
        $output = $testJson | & pwsh -File $ScriptPath 2>&1
        
        # Check if log file was created
        $day = (Get-Date).ToUniversalTime().ToString("yyyyMMdd")
        $logFile = Join-Path $testLogDir "events-$day.jsonl"
        
        if (Test-Path $logFile) {
            $logContent = Get-Content $logFile -Raw
            if ($logContent -match "test-session-123") {
                Write-TestResult -TestName $testName -Passed $true
                $cleanup = $true
            } else {
                Write-TestResult -TestName $testName -Passed $false -Message "Log file exists but doesn't contain expected data"
                $cleanup = $false
            }
        } else {
            Write-TestResult -TestName $testName -Passed $false -Message "Log file was not created"
            $cleanup = $false
        }
        
        # Cleanup
        if (Test-Path $testLogDir) {
            Remove-Item $testLogDir -Recurse -Force -ErrorAction SilentlyContinue
        }
        
        return $cleanup
    } catch {
        Write-TestResult -TestName $testName -Passed $false -Message "Exception: $_"
        return $false
    } finally {
        Remove-Item env:ZO_EVENT_LOG_DIR -ErrorAction SilentlyContinue
    }
}

function Test-ChromaIntegration {
    $testName = "ChromaDB Integration"
    
    if (-not $IntegrationTest) {
        Write-TestResult -TestName $testName -Passed $true -Message "Skipped (use -IntegrationTest to enable)"
        return $true
    }
    
    try {
        # Test if Chroma endpoint is accessible
        $response = Invoke-RestMethod -Uri "$ChromaEndpoint/health" -Method Get -TimeoutSec 5
        Write-TestResult -TestName $testName -Passed $true -Message "ChromaDB is accessible at $ChromaEndpoint"
        return $true
    } catch {
        Write-TestResult -TestName $testName -Passed $false -Message "Cannot reach ChromaDB: $_"
        return $false
    }
}

function Test-HookOutputFormat {
    param([string]$ScriptPath)
    
    $testName = "Hook Output Format: $(Split-Path $ScriptPath -Leaf)"
    
    $testJson = @{
        hook_event_name = "UserPromptSubmit"
        session_id = "test-session-123"
        tool_name = "mcp_test_tool"
        cwd = "e:/test/repo"
        prompt = "Test prompt"
    } | ConvertTo-Json -Depth 10 -Compress
    
    try {
        $output = $testJson | & pwsh -File $ScriptPath 2>&1
        
        # Check if output is valid JSON (if any output exists)
        if ($output) {
            try {
                $parsed = $output | ConvertFrom-Json
                if ($parsed.hookSpecificOutput) {
                    Write-TestResult -TestName $testName -Passed $true
                    return $true
                } else {
                    Write-TestResult -TestName $testName -Passed $false -Message "Output doesn't match expected format"
                    return $false
                }
            } catch {
                Write-TestResult -TestName $testName -Passed $false -Message "Output is not valid JSON: $output"
                return $false
            }
        } else {
            # No output is also valid (some hooks don't return JSON)
            Write-TestResult -TestName $testName -Passed $true -Message "No output (valid for this hook)"
            return $true
        }
    } catch {
        Write-TestResult -TestName $testName -Passed $false -Message "Exception: $_"
        return $false
    }
}

# Main test execution
Write-Host "=== Claude Code Hooks Test Framework ===" -ForegroundColor $Colors.Info
Write-Host "Testing hooks in: $HooksDir" -ForegroundColor $Colors.Info
Write-Host "Integration Test: $IntegrationTest" -ForegroundColor $Colors.Info
Write-Host ""

# Find all PowerShell hook scripts
$hookScripts = Get-ChildItem $HooksDir -Filter "*.ps1" -File

if ($hookScripts.Count -eq 0) {
    Write-Host "✗ No PowerShell hook scripts found in $HooksDir" -ForegroundColor $Colors.Error
    exit 1
}

Write-Host "Found $($hookScripts.Count) hook scripts to test" -ForegroundColor $Colors.Info
Write-Host ""

# Run tests for each hook script
foreach ($script in $hookScripts) {
    $scriptPath = $script.FullName
    $scriptName = $script.Name
    
    Write-Host "Testing: $scriptName" -ForegroundColor $Colors.Info
    Write-Host "----------------------------------------" -ForegroundColor $Colors.Debug
    
    # Run all tests for this script
    Test-PowerShellSyntax -ScriptPath $scriptPath
    Test-JsonInputHandling -ScriptPath $scriptPath
    Test-InvalidJsonHandling -ScriptPath $scriptPath
    Test-McpFiltering -ScriptPath $scriptPath
    Test-EventLogging -ScriptPath $scriptPath
    Test-HookOutputFormat -ScriptPath $scriptPath
    
    Write-Host ""
}

# Run integration tests
if ($IntegrationTest) {
    Write-Host "Running Integration Tests" -ForegroundColor $Colors.Info
    Write-Host "----------------------------------------" -ForegroundColor $Colors.Debug
    Test-ChromaIntegration
    Write-Host ""
}

# Summary
Write-Host "=== Test Summary ===" -ForegroundColor $Colors.Info
Write-Host "Total Tests: $($TestResults.Total)" -ForegroundColor $Colors.Info
Write-Host "Passed: $($TestResults.Passed)" -ForegroundColor $Colors.Pass
Write-Host "Failed: $($TestResults.Failed)" -ForegroundColor $Colors.Fail
Write-Host ""

if ($TestResults.Failed -gt 0) {
    Write-Host "Failed Tests:" -ForegroundColor $Colors.Error
    foreach ($detail in $TestResults.Details | Where-Object { -not $_.Passed }) {
        Write-Host "  - $($detail.TestName)" -ForegroundColor $Colors.Error
        if ($detail.Message) {
            Write-Host "    $($detail.Message)" -ForegroundColor $Colors.Debug
        }
    }
    Write-Host ""
}

# Exit with appropriate code
exit $(if ($TestResults.Failed -eq 0) { 0 } else { 1 })