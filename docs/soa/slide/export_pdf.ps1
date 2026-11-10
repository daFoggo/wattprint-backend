param($in,$pdf)
$p=New-Object -ComObject PowerPoint.Application
$d=$p.Presentations.Open($in,$true,$false,$false)
$d.SaveAs($pdf,32)
$d.Close(); $p.Quit()
