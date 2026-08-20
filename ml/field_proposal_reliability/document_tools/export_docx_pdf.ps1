param(
    [Parameter(Mandatory = $true)][string[]]$InputDocs,
    [Parameter(Mandatory = $true)][string]$OutputDir
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0

try {
    foreach ($inputDoc in $InputDocs) {
        $document = $null
        try {
            $document = $word.Documents.Open($inputDoc, $false, $true)
            $stem = [System.IO.Path]::GetFileNameWithoutExtension($inputDoc)
            $pdfPath = [System.IO.Path]::Combine($OutputDir, "$stem.pdf")
            $document.ExportAsFixedFormat($pdfPath, 17)
            Write-Output $pdfPath
        }
        finally {
            if ($null -ne $document) {
                $document.Close($false)
            }
        }
    }
}
finally {
    $word.Quit()
    [System.Runtime.Interopservices.Marshal]::ReleaseComObject($word) | Out-Null
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
