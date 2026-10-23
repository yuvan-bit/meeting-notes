param(
    [string]$Keytool = "",
    [string]$Alias = "meeting-notes"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$androidDir = Join-Path $root "android"
$keystoreDir = Join-Path $androidDir "keystore"
$keystoreFile = Join-Path $keystoreDir "release.jks"
$propertiesFile = Join-Path $androidDir "keystore.properties"

function Find-Keytool {
    if ($Keytool) {
        if (Test-Path -LiteralPath $Keytool) {
            return (Resolve-Path -LiteralPath $Keytool).Path
        }
        throw "指定的 keytool 不存在：$Keytool"
    }
    if ($env:JAVA_HOME) {
        $candidate = Join-Path $env:JAVA_HOME "bin\keytool.exe"
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    $command = Get-Command keytool.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $patterns = @(
        (Join-Path $env:USERPROFILE "Downloads\tools\jdk*\bin\keytool.exe"),
        "C:\Program Files\Java\jdk*\bin\keytool.exe",
        "C:\Program Files\Android\Android Studio\jbr\bin\keytool.exe"
    )
    foreach ($pattern in $patterns) {
        $found = Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    throw "找不到 keytool.exe，请安装 JDK 17，或用 -Keytool 指定路径。"
}

function Read-PlainPassword([string]$Prompt) {
    $secure = Read-Host -AsSecureString $Prompt
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

if ((Test-Path -LiteralPath $keystoreFile) -or (Test-Path -LiteralPath $propertiesFile)) {
    throw "签名配置已存在（$keystoreFile 或 $propertiesFile）。为避免覆盖旧密钥，脚本已停止。"
}

$keytoolPath = Find-Keytool
$password = Read-PlainPassword "设置 release 签名密码（至少 8 位，不会显示）"
$confirm = Read-PlainPassword "再次输入签名密码"
if ($password.Length -lt 8) { throw "密码至少 8 位。" }
if ($password -ne $confirm) { throw "两次输入的密码不一致。" }
if ($password -notmatch '^[A-Za-z0-9._@#$%^&*+=!?-]{8,}$') {
    throw "签名密码请使用字母、数字或 ._@#`$%^&*+=!?-，避免反斜杠、引号和冒号。"
}

New-Item -ItemType Directory -Path $keystoreDir -Force | Out-Null
$env:MEETING_KEYSTORE_PASS = $password
try {
    & $keytoolPath -genkeypair -v `
        -keystore $keystoreFile `
        -alias $Alias `
        -keyalg RSA -keysize 4096 -validity 10000 `
        -storepass:env MEETING_KEYSTORE_PASS `
        -keypass:env MEETING_KEYSTORE_PASS `
        -dname "CN=Meeting Notes, OU=Mobile, O=Meeting Notes, C=CN"
    if ($LASTEXITCODE -ne 0) {
        throw "keytool 执行失败，退出码 $LASTEXITCODE"
    }
} finally {
    Remove-Item Env:MEETING_KEYSTORE_PASS -ErrorAction SilentlyContinue
}

$content = @(
    "storeFile=keystore/release.jks",
    "storePassword=$password",
    "keyAlias=$Alias",
    "keyPassword=$password"
) -join "`r`n"
Set-Content -LiteralPath $propertiesFile -Value $content -Encoding ASCII -NoNewline

$jdkHome = Split-Path -Parent (Split-Path -Parent $keytoolPath)
Write-Host ""
Write-Host "已生成 release 签名密钥：$keystoreFile"
Write-Host "签名配置：$propertiesFile（已在 .gitignore 中）"
Write-Host "请备份 keystore 文件和签名密码；丢失后将无法覆盖安装后续版本。"
Write-Host "构建 release 前如 Gradle 找不到 Java，可先执行："
Write-Host "  `$env:JAVA_HOME = '$jdkHome'"
Write-Host "然后：cd android; .\gradlew assembleRelease"
