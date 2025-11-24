<#
.SYNOPSIS
    Automated deployment script for centralized Git hooks system
.DESCRIPTION
    Deploys hooks from central repository to multiple target repositories using symbolic links
#>

param(
    [Parameter(Mandatory=$true)]
    [string[]]$TargetRepos,
    
    [Parameter(Mandatory=$false)]
    [string]$CentralRepo = $PSScriptRoot,
    
    [Parameter(Mandatory=$false)]
    [string]$HooksDir = "hooks",
    
    [Parameter(Mandatory=$false)]
    [switch]$DryRun,
    
    [Parameter(Mandatory=$false)]
    [switch]$Force,
    
    [Parameter(Mandatory=$false)]
    [switch]$BackupExisting
)

# Color output
$Colors = @{
    Info = "Cyan"
    Success = "Green"
    Warning = "Yellow"
    Error = "Red"
    Debug = "Gray"
}

function Write-ColorOutput {
    param(
        [string]$Message,
        [string]$Color = "White"
    )
    Write-Host $Message -ForegroundColor $Colors[$Color]
}

function Test-IsAdministrator {
    $currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-IsSymlink {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $false }
    $item = Get-Item $Path
    return $item.LinkType -eq "SymbolicLink"
}

function New-SymbolicLink {
    param(
        [string]$Link,
        [string]$Target,
        [string]$ItemType = "File"
    )
    
    try {
        if (Test-Path $Link) {
            if ($Force) {
                Remove-Item $Link -Force -Recurse -ErrorAction Stop
            } else {
                throw "Path already exists: $Link"
            }
        }
        
        # Create symbolic link
        if ($ItemType -eq "Directory") {
            New-Item -ItemType SymbolicLink -Path $Link -Target $Target -Force | Out-Null
        } else {
            New-Item -ItemType SymbolicLink -Path $Link -Target $Target -Force | Out-Null
        }
        
        return $true
    } catch {
        Write-ColorOutput "Failed to create symlink: $_" "Error"
        return $false
    }
}

function Backup-Hooks {
    param(
        [string]$RepoPath,
        [string]$BackupDir
    )
    
    $hooksPath = Join-Path $RepoPath ".git\hooks"
    if (-not (Test-Path $hooksPath)) {
        return $true
    }
    
    try {
        $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $backupPath = Join-Path $BackupDir "hooks_backup_$timestamp"
        
        if (-not (Test-Path $backupPath)) {
            New-Item -ItemType Directory -Path $backupPath -Force | Out-Null
        }
        
        # Copy existing hooks to backup
        Get-ChildItem $hooksPath -File | ForEach-Object {
            Copy-Item $_.FullName -Destination $backupPath -Force
        }
        
        Write-ColorOutput "✓ Backed up existing hooks to: $backupPath" "Success"
        return $true
    } catch {
        Write-ColorOutput "✗ Failed to backup hooks: $_" "Error"
        return $false
    }
}

function Deploy-HooksToRepo {
    param(
        [string]$RepoPath,
        [string]$CentralHooksPath
    )
    
    Write-ColorOutput "`nDeploying hooks to: $RepoPath" "Info"
    
    # Verify repository
    $gitDir = Join-Path $RepoPath ".git"
    if (-not (Test-Path $gitDir)) {
        Write-ColorOutput "✗ Not a Git repository: $RepoPath" "Error"
        return $false
    }
    
    $hooksDir = Join-Path $gitDir "hooks"
    if (-not (Test-Path $hooksDir)) {
        try {
            New-Item -ItemType Directory -Path $hooksDir -Force | Out-Null
        } catch {
            Write-ColorOutput "✗ Failed to create hooks directory: $_" "Error"
            return $false
        }
    }
    
    # Backup existing hooks if requested
    if ($BackupExisting) {
        $backupDir = Join-Path $RepoPath ".git\hook_backups"
        if (-not (Backup-Hooks -RepoPath $RepoPath -BackupDir $backupDir)) {
            if (-not $Force) {
                return $false
            }
        }
    }
    
    # Get hook files from central repository
    $hookFiles = Get-ChildItem $CentralHooksPath -File | Where-Object {
        $_.Extension -in @(".ps1", ".py")
    }
    
    if ($hookFiles.Count -eq 0) {
        Write-ColorOutput "✗ No hook files found in central repository" "Error"
        return $false
    }
    
    $successCount = 0
    $totalCount = $hookFiles.Count
    
    foreach ($hookFile in $hookFiles) {
        $hookName = [System.IO.Path]::GetFileNameWithoutExtension($hookFile.Name)
        $targetHookPath = Join-Path $hooksDir $hookName
        
        # Remove extension for PowerShell hooks (Git hooks don't use extensions)
        if ($hookFile.Extension -eq ".ps1") {
            $targetHookPath = $targetHookPath -replace '\.ps1$', ''
        } elseif ($hookFile.Extension -eq ".py") {
            $targetHookPath = $targetHookPath -replace '\.py$', ''
        }
        
        Write-ColorOutput "  → Creating symlink: $targetHookPath" "Debug"
        
        if ($DryRun) {
            Write-ColorOutput "    [DRY RUN] Would create symlink to: $($hookFile.FullName)" "Warning"
            $successCount++
        } else {
            if (New-SymbolicLink -Link $targetHookPath -Target $hookFile.FullName -ItemType "File") {
                # Make hook executable (Git on Windows respects this)
                try {
                    attrib +R $targetHookPath | Out-Null
                } catch {
                    # Ignore errors with attributes
                }
                $successCount++
                Write-ColorOutput "    ✓ Created symlink" "Success"
            } else {
                Write-ColorOutput "    ✗ Failed to create symlink" "Error"
            }
        }
    }
    
    Write-ColorOutput "`n✓ Deployed $successCount/$totalCount hooks to: $RepoPath" "Success"
    return $true
}

function Create-WindowsShortcut {
    param(
        [string]$LinkPath,
        [string]$TargetPath,
        [string]$Arguments = ""
    )
    
    try {
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($LinkPath)
        $shortcut.TargetPath = $TargetPath
        if ($Arguments) {
            $shortcut.Arguments = $Arguments
        }
        $shortcut.Save()
        return $true
    } catch {
        Write-ColorOutput "Failed to create shortcut: $_" "Error"
        return $false
    }
}

# Main execution
Write-ColorOutput "=== Claude Code Hooks Deployment Script ===" "Info"
Write-ColorOutput "Central Repository: $CentralRepo" "Info"
Write-ColorOutput "Target Repositories: $($TargetRepos.Count)" "Info"
Write-ColorOutput "Dry Run: $DryRun" "Info"
Write-ColorOutput "Force: $Force" "Info"
Write-ColorOutput "Backup Existing: $BackupExisting" "Info"

# Verify central repository
$centralHooksPath = Join-Path $CentralRepo $HooksDir
if (-not (Test-Path $centralHooksPath)) {
    Write-ColorOutput "✗ Central hooks directory not found: $centralHooksPath" "Error"
    exit 1
}

Write-ColorOutput "`n✓ Found central hooks directory: $centralHooksPath" "Success"

# Check if running as administrator (required for symlinks on some systems)
if (-not (Test-IsAdministrator)) {
    Write-ColorOutput "⚠ Not running as administrator. Symlink creation may fail on some systems." "Warning"
    Write-ColorOutput "  Consider running this script as administrator." "Warning"
}

# Deploy to each target repository
$overallSuccess = $true
$successCount = 0

foreach ($targetRepo in $TargetRepos) {
    # Resolve relative paths
    $repoPath = Resolve-Path $targetRepo -ErrorAction SilentlyContinue
    if (-not $repoPath) {
        $repoPath = $targetRepo
    }
    
    if (Deploy-HooksToRepo -RepoPath $repoPath -CentralHooksPath $centralHooksPath) {
        $successCount++
    } else {
        $overallSuccess = $false
    }
}

# Summary
Write-ColorOutput "`n=== Deployment Summary ===" "Info"
Write-ColorOutput "Successfully deployed to: $successCount/$($TargetRepos.Count) repositories" $(if ($overallSuccess) { "Success" } else { "Warning" })

if ($DryRun) {
    Write-ColorOutput "`n⚠ This was a DRY RUN. No actual changes were made." "Warning"
    Write-ColorOutput "  Run without -DryRun to apply changes." "Warning"
}

exit $(if ($overallSuccess) { 0 } else { 1 })