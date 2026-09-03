#requires -version 3.0
<#
    RDO Lobby Manager setup, for people running from a clone of the source.

    This draws a real window: a welcome page with options, a progress page
    with a live log, and a finish page. There is no console. Everyone else
    should use RDO-Lobby-Manager-Setup-x.y.z.exe from the Releases page,
    which needs no Python at all.

    Two rules this file has to keep, both learned the hard way from
    Icarus-Save-Editor's installer (see that project's packaging/
    install-from-source.ps1 for the same rules with the original incident
    reports):

    1. Every path is built from $root, the repo root, which is the PARENT
       of the folder this script lives in. Resolving to the script's own
       directory is what shipped broken -- `pip install -e .` ran inside
       packaging\, which has no pyproject.toml, and setup died with
       "does not appear to be a Python project".

    2. This file stays ASCII. Windows PowerShell reads a .ps1 with no byte
       order mark as ANSI, so a UTF-8 em dash in a string came out on
       screen as three mojibake characters. Anything typographic is built
       at runtime from a character code instead. tests/test_installer.py
       holds both rules.

    Nothing here needs administrator rights: everything lands in a .venv
    beside pyproject.toml, and the only thing written outside the repo is
    a shortcut.
#>

[CmdletBinding()]
param(
    # Reinstall over a working setup without re-creating the .venv.
    [switch]$Reinstall
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
#  Where things are
# ---------------------------------------------------------------------------

$here = $PSCommandPath
if (-not $here) { $here = $MyInvocation.MyCommand.Path }
$script:root = Split-Path -Parent (Split-Path -Parent $here)

$script:VenvDir  = Join-Path $script:root '.venv'
$script:VenvPy   = Join-Path $script:VenvDir 'Scripts\python.exe'
$script:VenvIse  = Join-Path $script:VenvDir 'Scripts\rdo-lobby-manager.exe'
$script:StartBat = Join-Path $script:root 'Start RDO Lobby Manager.bat'

# ---------------------------------------------------------------------------
#  Native bits: hiding the console, a crisp window, a themed progress bar
#
#  All of it is optional. If this block will not compile the installer
#  still runs -- it just looks more ordinary -- so every use is guarded
#  on $Native.
# ---------------------------------------------------------------------------

$script:Native = $null
try {
    Add-Type -Namespace RdoLmSetup -Name Win -UsingNamespace System.Runtime.InteropServices `
             -MemberDefinition @'
[DllImport("kernel32.dll")]
public static extern IntPtr GetConsoleWindow();
[DllImport("user32.dll")]
public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
[DllImport("user32.dll")]
public static extern bool SetProcessDPIAware();
[DllImport("uxtheme.dll", CharSet = CharSet.Unicode)]
public static extern int SetWindowTheme(IntPtr hWnd, string app, string idlist);
[DllImport("dwmapi.dll")]
public static extern int DwmSetWindowAttribute(IntPtr hWnd, int attr, ref int value, int size);
'@ -ErrorAction Stop
    $script:Native = [RdoLmSetup.Win]
} catch {
    $script:Native = $null
}

function Set-ConsoleVisible {
    param([bool]$Visible)
    if (-not $script:Native) { return }
    try {
        $h = $script:Native::GetConsoleWindow()
        if ($h -ne [IntPtr]::Zero) {
            $mode = 0
            if ($Visible) { $mode = 5 }
            [void]$script:Native::ShowWindow($h, $mode)
        }
    } catch { }
}

if ($script:Native) { try { [void]$script:Native::SetProcessDPIAware() } catch { } }

# ---------------------------------------------------------------------------
#  The window
# ---------------------------------------------------------------------------

try {
    Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
    Add-Type -AssemblyName System.Drawing -ErrorAction Stop
} catch {
    Write-Host ''
    Write-Host '  Setup could not open its window.' -ForegroundColor Red
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ''
    Read-Host '  Press Enter to close'
    exit 1
}

[System.Windows.Forms.Application]::EnableVisualStyles()
[System.Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)

# There is a window from here on, so the console can go. The flag tells
# Install.bat the same thing: everything from now on is reported on screen,
# so it must not stop for a keypress at a console the user can no longer
# see.
$tempDir = $env:TEMP
if (-not $tempDir) { $tempDir = [System.IO.Path]::GetTempPath() }
$script:GuiFlag = Join-Path $tempDir 'rdo-lm-setup-window.flag'
try { Set-Content -LiteralPath $script:GuiFlag -Value 'up' -Encoding ASCII } catch { }
Set-ConsoleVisible $false

function Get-Rgb { param([int]$R, [int]$G, [int]$B) [System.Drawing.Color]::FromArgb($R, $G, $B) }

# The same dark palette Icarus uses, so both installers look like they
# came from the same place.
$cBg      = Get-Rgb 10 13 20
$cPanel   = Get-Rgb 15 20 32
$cField   = Get-Rgb 22 28 42
$cBorder  = Get-Rgb 42 51 71
$cText    = Get-Rgb 232 236 244
$cMuted   = Get-Rgb 148 160 184
$cFaint   = Get-Rgb 82 94 116
$cAccent  = Get-Rgb 34 211 238
$cAccentD = Get-Rgb 14 165 196
$cGood    = Get-Rgb 52 211 153
$cBad     = Get-Rgb 248 113 113

$fBase  = New-Object System.Drawing.Font('Segoe UI', 9)
$fTitle = New-Object System.Drawing.Font('Segoe UI', 15, [System.Drawing.FontStyle]::Bold)
$fHead  = New-Object System.Drawing.Font('Segoe UI', 12, [System.Drawing.FontStyle]::Bold)
$fSmall = New-Object System.Drawing.Font('Segoe UI', 8.25)
$fMono  = New-Object System.Drawing.Font('Consolas', 8.25)

# Em dash built at runtime from the code point -- see file-level comment,
# rule 2. A literal em dash in this file would be mojibake on screen.
$emDash = [string][char]0x2014

$FormW    = 620
$FormH    = 500
$LogExtra = 200
$LogTop   = 356
$LinkTop  = 326

$form = New-Object System.Windows.Forms.Form
$form.Text = 'RDO Lobby Manager Setup'
$form.ClientSize = New-Object System.Drawing.Size($FormW, $FormH)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.BackColor = $cBg
$form.ForeColor = $cText
$form.Font = $fBase

# Top panel: title
$pnlHeader = New-Object System.Windows.Forms.Panel
$pnlHeader.Dock = 'Top'
$pnlHeader.Height = 64
$pnlHeader.BackColor = $cPanel
$form.Controls.Add($pnlHeader)

$lblTitle = New-Object System.Windows.Forms.Label
$lblTitle.Text = 'RDO Lobby Manager'
$lblTitle.Font = $fTitle
$lblTitle.ForeColor = $cText
$lblTitle.AutoSize = $true
$lblTitle.Location = New-Object System.Drawing.Point(20, 14)
$pnlHeader.Controls.Add($lblTitle)

$lblSubtitle = New-Object System.Windows.Forms.Label
$lblSubtitle.Text = "Setup $emDash installing from source"
$lblSubtitle.Font = $fSmall
$lblSubtitle.ForeColor = $cMuted
$lblSubtitle.AutoSize = $true
$lblSubtitle.Location = New-Object System.Drawing.Point(22, 42)
$pnlHeader.Controls.Add($lblSubtitle)

# Welcome page body
$lblWelcome = New-Object System.Windows.Forms.Label
$lblWelcome.Text = "This will set up RDO Lobby Manager on this computer.$emDash"
$lblWelcome.AutoSize = $false
$lblWelcome.Location = New-Object System.Drawing.Point(24, 88)
$lblWelcome.Size = New-Object System.Drawing.Size($FormW - 48, 22)
$lblWelcome.ForeColor = $cText
$form.Controls.Add($lblWelcome)

$lblWelcomeBody = New-Object System.Windows.Forms.Label
$lblWelcomeBody.Text = @"
RDO Lobby Manager edits Red Dead Redemption 2's startup.meta so you can hop into a friend's private lobby without typing the password on the game's on-screen keyboard. Passphrases are Fernet-encrypted with a key derived from your Windows account; the original startup.meta is backed up before the first change.

Everything installs into a .venv beside this folder. Nothing is written outside the repo except a Start menu shortcut. No administrator rights are needed.
"@
$lblWelcomeBody.AutoSize = $false
$lblWelcomeBody.Location = New-Object System.Drawing.Point(24, 114)
$lblWelcomeBody.Size = New-Object System.Drawing.Size($FormW - 48, 120)
$lblWelcomeBody.ForeColor = $cMuted
$form.Controls.Add($lblWelcomeBody)

# Status / progress page
$lblStatus = New-Object System.Windows.Forms.Label
$lblStatus.Text = "Ready to install"
$lblStatus.Font = $fHead
$lblStatus.ForeColor = $cText
$lblStatus.AutoSize = $true
$lblStatus.Location = New-Object System.Drawing.Point(24, 88)
$lblStatus.Visible = $false
$form.Controls.Add($lblStatus)

$lblStep = New-Object System.Windows.Forms.Label
$lblStep.Text = ''
$lblStep.Font = $fSmall
$lblStep.ForeColor = $cMuted
$lblStep.AutoSize = $true
$lblStep.Location = New-Object System.Drawing.Point(24, 116)
$lblStep.Visible = $false
$form.Controls.Add($lblStep)

$progress = New-Object System.Windows.Forms.ProgressBar
$progress.Style = 'Continuous'
$progress.Minimum = 0
$progress.Maximum = 100
$progress.Value = 0
$progress.Location = New-Object System.Drawing.Point(24, 140)
$progress.Size = New-Object System.Drawing.Size($FormW - 48, 18)
$progress.Visible = $false
$form.Controls.Add($progress)

# Live log
$txtLog = New-Object System.Windows.Forms.TextBox
$txtLog.Multiline = $true
$txtLog.ReadOnly = $true
$txtLog.ScrollBars = 'Vertical'
$txtLog.WordWrap = $true
$txtLog.BackColor = $cField
$txtLog.ForeColor = $cText
$txtLog.BorderStyle = 'FixedSingle'
$txtLog.Font = $fMono
$txtLog.Location = New-Object System.Drawing.Point(24, $LogTop)
$txtLog.Size = New-Object System.Drawing.Size($FormW - 48, 100)
$txtLog.Visible = $false
$form.Controls.Add($txtLog)

# Finish page
$lblFinish = New-Object System.Windows.Forms.Label
$lblFinish.Text = "Installation complete"
$lblFinish.Font = $fTitle
$lblFinish.ForeColor = $cGood
$lblFinish.AutoSize = $true
$lblFinish.Location = New-Object System.Drawing.Point(24, 96)
$lblFinish.Visible = $false
$form.Controls.Add($lblFinish)

$lblFinishBody = New-Object System.Windows.Forms.Label
$lblFinishBody.Text = "You can start RDO Lobby Manager from the Start menu, the Desktop shortcut, or by double-clicking 'Start RDO Lobby Manager.bat' in this folder."
$lblFinishBody.AutoSize = $false
$lblFinishBody.Location = New-Object System.Drawing.Point(24, 132)
$lblFinishBody.Size = New-Object System.Drawing.Size($FormW - 48, 60)
$lblFinishBody.ForeColor = $cMuted
$lblFinishBody.Visible = $false
$form.Controls.Add($lblFinishBody)

# Bottom panel: buttons
$pnlFooter = New-Object System.Windows.Forms.Panel
$pnlFooter.Dock = 'Bottom'
$pnlFooter.Height = 56
$pnlFooter.BackColor = $cPanel
$form.Controls.Add($pnlFooter)

$btnNext = New-Object System.Windows.Forms.Button
$btnNext.Text = 'Install'
$btnNext.Size = New-Object System.Drawing.Size(110, 32)
$btnNext.Location = New-Object System.Drawing.Point($FormW - 130, 12)
$btnNext.FlatStyle = 'Flat'
$btnNext.BackColor = $cAccentD
$btnNext.ForeColor = $cText
$btnNext.FlatAppearance.BorderSize = 0
$pnlFooter.Controls.Add($btnNext)

$btnCancel = New-Object System.Windows.Forms.Button
$btnCancel.Text = 'Cancel'
$btnCancel.Size = New-Object System.Drawing.Size(90, 32)
$btnCancel.Location = New-Object System.Drawing.Point($FormW - 250, 12)
$btnCancel.FlatStyle = 'Flat'
$btnCancel.BackColor = $cPanel
$btnCancel.ForeColor = $cMuted
$btnCancel.FlatAppearance.BorderColor = $cBorder
$pnlFooter.Controls.Add($btnCancel)

# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

function Show-Welcome {
    $lblWelcome.Visible = $true
    $lblWelcomeBody.Visible = $true
    $lblStatus.Visible = $false
    $lblStep.Visible = $false
    $progress.Visible = $false
    $txtLog.Visible = $false
    $lblFinish.Visible = $false
    $lblFinishBody.Visible = $false
    $btnNext.Text = 'Install'
    $btnNext.Enabled = $true
    $form.ClientSize = New-Object System.Drawing.Size($FormW, $FormH)
}

function Show-Progress {
    param([string]$Status, [string]$Step)
    $lblWelcome.Visible = $false
    $lblWelcomeBody.Visible = $false
    $lblStatus.Visible = $true
    $lblStatus.Text = $Status
    $lblStep.Visible = $true
    $lblStep.Text = $Step
    $progress.Visible = $true
    $progress.Value = 0
    $txtLog.Visible = $true
    $lblFinish.Visible = $false
    $lblFinishBody.Visible = $false
    $btnNext.Enabled = $false
    $form.ClientSize = New-Object System.Drawing.Size($FormW, $FormH + $LogExtra)
    [System.Windows.Forms.Application]::DoEvents()
}

function Show-Finish {
    param([string]$Message, [bool]$Success)
    $lblWelcome.Visible = $false
    $lblWelcomeBody.Visible = $false
    $lblStatus.Visible = $false
    $lblStep.Visible = $false
    $progress.Visible = $false
    $txtLog.Visible = $true
    $lblFinish.Visible = $true
    $lblFinish.Text = if ($Success) { "Installation complete" } else { "Installation failed" }
    $lblFinish.ForeColor = if ($Success) { $cGood } else { $cBad }
    $lblFinishBody.Visible = $true
    $lblFinishBody.Text = $Message
    $btnNext.Text = 'Close'
    $btnNext.Enabled = $true
}

function Write-Log {
    param([string]$Line)
    $stamp = (Get-Date).ToString('HH:mm:ss')
    $txtLog.AppendText("[$stamp] $Line`r`n")
    $txtLog.SelectionStart = $txtLog.Text.Length
    $txtLog.ScrollToCaret()
    [System.Windows.Forms.Application]::DoEvents()
}

function Set-Progress {
    param([int]$Percent)
    $progress.Value = [Math]::Max(0, [Math]::Min(100, $Percent))
    [System.Windows.Forms.Application]::DoEvents()
}

function Test-Python {
    # Find a Python 3.12+ on PATH. Returns the full path, or $null.
    $candidates = @('python', 'python3', 'py')
    foreach ($name in $candidates) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        try {
            $ver = & $cmd.Source --version 2>&1
            if ($ver -match 'Python (\d+)\.(\d+)') {
                $major = [int]$Matches[1]
                $minor = [int]$Matches[2]
                if ($major -ge 3 -and $minor -ge 12) {
                    return $cmd.Source
                }
            }
        } catch { }
    }
    return $null
}

function Install-Python {
    # Last-resort installer via winget. The Install.bat caller may have
    # already failed here, so the function reports success/failure back
    # to the GUI rather than throwing.
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) { return $false }
    Write-Log "Python 3.12+ not found on PATH. Trying winget..."
    $p = Start-Process -FilePath $winget.Source -ArgumentList @(
        'install', '--id', 'Python.Python.3.12',
        '--accept-package-agreements', '--accept-source-agreements',
        '-e', 'C:\Python312', '--silent'
    ) -Wait -PassThru -NoNewWindow
    return ($p.ExitCode -eq 0)
}

function New-Venv {
    param([string]$Python)
    if (Test-Path $script:VenvDir) { return }
    Write-Log "Creating virtual environment at .venv\"
    & $Python -m venv $script:VenvDir
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed (exit $LASTEXITCODE)" }
}

function Install-Deps {
    Write-Log "Upgrading pip..."
    & $script:VenvPy -m pip install --upgrade pip --quiet
    if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed (exit $LASTEXITCODE)" }

    Write-Log "Installing rdo-lobby-manager (editable)..."
    & $script:VenvPy -m pip install -e . --quiet
    if ($LASTEXITCODE -ne 0) { throw "pip install -e . failed (exit $LASTEXITCODE)" }

    Write-Log "Verifying install..."
    & $script:VenvPy -c "import rdo_lobby_manager; print('import ok')"
    if ($LASTEXITCODE -ne 0) { throw "import verification failed" }
}

function New-Shortcuts {
    # Best-effort Start menu entry. Per-user (no admin), so we write
    # under %APPDATA%\Microsoft\Windows\Start Menu\Programs.
    $startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
    if (-not (Test-Path $startMenu)) { return }
    $shortcutPath = Join-Path $startMenu 'RDO Lobby Manager.lnk'

    try {
        $ws = New-Object -ComObject WScript.Shell
        $sc = $ws.CreateShortcut($shortcutPath)
        $sc.TargetPath = $script:VenvIse
        $sc.WorkingDirectory = $script:root
        $sc.Description = "RDO Lobby Manager"
        $sc.Save()
        Write-Log "Start menu shortcut created."
    } catch {
        Write-Log "Start menu shortcut failed (non-fatal): $($_.Exception.Message)"
    }
}

# ---------------------------------------------------------------------------
#  Click handlers
# ---------------------------------------------------------------------------

$script:Cancelled = $false
$btnCancel.Add_Click({
    $script:Cancelled = $true
    $form.Close()
})

$btnNext.Add_Click({
    if ($btnNext.Text -eq 'Close') {
        $form.Close()
        return
    }

    # Transition to the progress page
    Show-Progress -Status "Installing..." -Step "Preparing"
    Set-Progress 5

    try {
        # 1. Find or install Python
        Write-Log "Checking for Python 3.12+..."
        $py = Test-Python
        if (-not $py) {
            Write-Log "Python 3.12+ not found. Attempting to install via winget..."
            if (-not (Install-Python)) {
                throw "Python 3.12+ is required. Install it from https://www.python.org/downloads/ and re-run setup."
            }
            $py = Test-Python
            if (-not $py) { throw "Python install succeeded but the new python.exe is not on PATH. Re-open this window and try again." }
        }
        Write-Log "Found Python: $py"
        Set-Progress 15

        if ($script:Cancelled) { return }

        # 2. Create or reuse venv
        if (Test-Path $script:VenvPy) {
            Write-Log "Existing .venv found, reusing."
        } else {
            New-Venv -Python $py
        }
        Set-Progress 35

        if ($script:Cancelled) { return }

        # 3. Install deps
        Install-Deps
        Set-Progress 85

        # 4. Shortcuts
        New-Shortcuts
        Set-Progress 100

        Show-Finish -Message "Double-click the Start menu shortcut, the Desktop shortcut, or 'Start RDO Lobby Manager.bat' in this folder to launch." -Success $true
    } catch {
        Write-Log "FAILED: $($_.Exception.Message)"
        Show-Finish -Message "$($_.Exception.Message)`r`n`r`nSee the log above for details." -Success $false
    }
})

# Initial state
Show-Welcome

# Wire form close (X button) to cancel
$form.Add_FormClosing({
    if ($btnNext.Text -ne 'Close') {
        $script:Cancelled = $true
    }
})

# Show
[void]$form.ShowDialog()

# Cleanup
try { Remove-Item -LiteralPath $script:GuiFlag -ErrorAction SilentlyContinue } catch { }

if ($script:Cancelled -and $btnNext.Text -ne 'Close') {
    exit 1
}
exit 0
