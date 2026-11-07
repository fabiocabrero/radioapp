# Limpeza de ambiente de teste do IC-7300 Station (so para quem esta testando a instalacao).
# Abra pelo arquivo Limpar-Teste-IC7300.bat (duplo clique). Nada e removido sem voce marcar e confirmar.
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$appId = '{6B2F5E1E-7C0A-4B0D-9E75-1C7300A5710A}_is1'
$regPaths = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$appId",
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$appId",
    "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\$appId"
)
$reg = $regPaths | Where-Object { Test-Path $_ } | Select-Object -First 1
$dataDir = Join-Path $env:APPDATA 'IC7300App'
$winget = (Get-Command winget -ErrorAction SilentlyContinue).Source
$terceiros = [ordered]@{
    'WSJT-X'          = 'JoeTaylor.WSJT-X'
    'JS8Call'         = 'KN4CRD.JS8Call'
    'fldigi'          = 'w1hkj.fldigi'
    'Winlink Express' = 'Winlink.WinlinkExpress'
    'FreeDV'          = 'FreeDV.FreeDV'
}

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Limpar teste - IC-7300 Station'
$form.Size = New-Object System.Drawing.Size(560, 520)
$form.StartPosition = 'CenterScreen'
$form.Font = New-Object System.Drawing.Font('Segoe UI', 10)

$lbl = New-Object System.Windows.Forms.Label
$lbl.Text = "Marque o que deseja remover deste computador.`nO que nao estiver instalado aparece desmarcado e desativado."
$lbl.Location = '12,10'; $lbl.Size = '520,44'
$form.Controls.Add($lbl)

$y = 60
function Add-Check($texto, $marcado, $habilitado) {
    $c = New-Object System.Windows.Forms.CheckBox
    $c.Text = $texto; $c.Checked = ($marcado -and $habilitado); $c.Enabled = $habilitado
    $c.Location = New-Object System.Drawing.Point(16, $script:y); $c.Size = '510,26'
    $form.Controls.Add($c); $script:y += 30
    return $c
}

$cApp  = Add-Check 'O programa IC-7300 Station (desinstalar)' $true ([bool]$reg)
$cData = Add-Check "Configuracoes, log e modelos de voz ($dataDir)" $true (Test-Path $dataDir)

$cTerc = @{}
if ($winget) {
    $lbl2 = New-Object System.Windows.Forms.Label
    $lbl2.Text = 'Programas de terceiros instalados (deixe desmarcado se ja os usava antes do teste):'
    $lbl2.Location = New-Object System.Drawing.Point(12, ($y + 6)); $lbl2.Size = '520,24'
    $form.Controls.Add($lbl2); $y += 34
    foreach ($nome in $terceiros.Keys) {
        & $winget list --id $terceiros[$nome] --exact --accept-source-agreements *> $null
        $achou = ($LASTEXITCODE -eq 0)
        $texto = $nome; if (-not $achou) { $texto += ' (nao instalado)' }
        $cTerc[$nome] = Add-Check $texto $false $achou
    }
}

$log = New-Object System.Windows.Forms.TextBox
$log.Multiline = $true; $log.ReadOnly = $true; $log.ScrollBars = 'Vertical'
$log.Location = New-Object System.Drawing.Point(16, ($y + 10)); $log.Size = '510,120'
$form.Controls.Add($log)
function Say($t) { $log.AppendText("$t`r`n"); [System.Windows.Forms.Application]::DoEvents() }

$btn = New-Object System.Windows.Forms.Button
$btn.Text = 'Limpar selecionados'; $btn.Location = New-Object System.Drawing.Point(16, ($y + 140)); $btn.Size = '200,34'
$btnCancel = New-Object System.Windows.Forms.Button
$btnCancel.Text = 'Fechar'; $btnCancel.Location = New-Object System.Drawing.Point(226, ($y + 140)); $btnCancel.Size = '100,34'
$btnCancel.Add_Click({ $form.Close() })
$form.Controls.AddRange(@($btn, $btnCancel))

$btn.Add_Click({
    $resp = [System.Windows.Forms.MessageBox]::Show('Remover os itens marcados? Isso nao pode ser desfeito.', 'Confirmar', 'YesNo', 'Warning')
    if ($resp -ne 'Yes') { return }
    $btn.Enabled = $false
    Get-Process -Name 'IC7300Station' -ErrorAction SilentlyContinue | ForEach-Object { Say 'Fechando o IC-7300 Station em execucao...'; $_ | Stop-Process -Force }

    if ($cApp.Checked) {
        $u = (Get-ItemProperty $reg).UninstallString
        $exe = $u -replace '^"([^"]+)".*$', '$1'
        Say 'Desinstalando o programa...'
        try { Start-Process -FilePath $exe -ArgumentList '/VERYSILENT', '/NORESTART' -Wait; Say 'Programa removido.' }
        catch { Say "ERRO ao desinstalar: $($_.Exception.Message)" }
    }
    if ($cData.Checked) {
        try { Remove-Item -LiteralPath $dataDir -Recurse -Force -ErrorAction Stop; Say 'Dados do usuario removidos.' }
        catch { Say "ERRO ao apagar ${dataDir}: $($_.Exception.Message)" }
    }
    foreach ($nome in $cTerc.Keys) {
        if ($cTerc[$nome].Checked) {
            Say "Desinstalando $nome (pode pedir permissao de administrador)..."
            & $winget uninstall --id $terceiros[$nome] --exact --silent --accept-source-agreements *> $null
            if ($LASTEXITCODE -eq 0) { Say "$nome removido." } else { Say "Nao consegui remover $nome (codigo $LASTEXITCODE). Remova em Configuracoes > Aplicativos." }
        }
    }
    Say 'Concluido. Pode fechar esta janela.'
})

[void]$form.ShowDialog()
