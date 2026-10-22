$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech

$root = Split-Path -Parent $PSScriptRoot
$sampleDir = Join-Path $root "data\samples"
New-Item -ItemType Directory -Force -Path $sampleDir | Out-Null

$segments = @(
    @{ Speaker = "A"; Text = "大家好，今天开会主要确认第三季度产品上线时间，还有测试资源的安排。" },
    @{ Speaker = "B"; Text = "我先同步一下进度，核心功能已经完成百分之八十，剩下的主要是支付和权限模块。" },
    @{ Speaker = "C"; Text = "测试这边需要两周做回归，如果下周才能提测，上线时间就要往后推。" },
    @{ Speaker = "A"; Text = "那我们先把上线时间定在十一月十五号，风险是支付模块的联调。" },
    @{ Speaker = "B"; Text = "支付联调我可以负责，但需要风控团队在十月底前给出接口。" },
    @{ Speaker = "C"; Text = "测试环境本周五可以准备好，我会把用例发到群里。" },
    @{ Speaker = "A"; Text = "好，结论就是十一月十五号上线，支付联调由我跟进，测试环境周五前就绪。" }
)

$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
    16000,
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
    [System.Speech.AudioFormat.AudioChannel]::Mono
)

$concatLines = New-Object System.Collections.Generic.List[string]
$index = 0
foreach ($segment in $segments) {
    $index++
    $raw = Join-Path $sampleDir ("_raw_{0:D2}.wav" -f $index)
    $out = Join-Path $sampleDir ("_seg_{0:D2}.wav" -f $index)

    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $synth.SelectVoice("Microsoft Huihui Desktop")
    $synth.Rate = 0
    $synth.SetOutputToWaveFile($raw, $format)
    $synth.Speak($segment.Text)
    $synth.Dispose()

    $filter = switch ($segment.Speaker) {
        "B" { "asetrate=16000*1.12,aresample=16000,atempo=0.892857" }
        "C" { "asetrate=16000*0.90,aresample=16000,atempo=1.111111" }
        default { $null }
    }

    if ($filter) {
        & ffmpeg -y -hide_banner -loglevel error -i $raw -filter:a $filter -ac 1 -ar 16000 -c:a pcm_s16le $out
    } else {
        & ffmpeg -y -hide_banner -loglevel error -i $raw -ac 1 -ar 16000 -c:a pcm_s16le $out
    }
    $concatLines.Add("file '$($out -replace '\\', '/')'")
}

$silence = Join-Path $sampleDir "_silence.wav"
& ffmpeg -y -hide_banner -loglevel error -f lavfi -i anullsrc=r=16000:cl=mono -t 0.35 -c:a pcm_s16le $silence

$withSilence = New-Object System.Collections.Generic.List[string]
foreach ($line in $concatLines) {
    $withSilence.Add($line)
    $withSilence.Add("file '$($silence -replace '\\', '/')'")
}

$listPath = Join-Path $sampleDir "_concat.txt"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($listPath, $withSilence, $utf8NoBom)

$demo = Join-Path $sampleDir "demo_meeting.wav"
& ffmpeg -y -hide_banner -loglevel error -f concat -safe 0 -i $listPath -c:a pcm_s16le $demo
if (!(Test-Path $demo)) { throw "ffmpeg did not create $demo" }

Get-ChildItem $sampleDir -Filter "_*" | Remove-Item -Force
Write-Output "Generated: $demo"
& ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 $demo

