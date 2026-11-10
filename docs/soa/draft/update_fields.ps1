param($in,$out,$pdf)
$w=New-Object -ComObject Word.Application; $w.Visible=$false; $w.DisplayAlerts=0
$d=$w.Documents.Open($in)
$d.Repaginate()
foreach($t in $d.TablesOfContents){ $t.Update() }
$d.Fields.Update() | Out-Null
foreach($t in $d.TablesOfContents){ $t.Update() }
$d.SaveAs2($out,16)
$d.ExportAsFixedFormat($pdf,17)
"pages: " + $d.ComputeStatistics(2)
$d.Close($false); $w.Quit()
