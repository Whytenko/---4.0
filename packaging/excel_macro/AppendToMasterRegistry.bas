Sub AppendToMasterRegistry()
    ' Это отдельный, неизменяемый файл-лаунчер (не наш сгенерированный
    ' отчёт!) — Python-код его больше не трогает, поэтому просим выбрать
    ' ОБА файла: сначала отчёт-источник ("Реестр"), потом реестр-назначение.
    Dim reportPath As Variant
    reportPath = Application.GetOpenFilename( _
        "Excel Files (*.xlsx;*.xlsm),*.xlsx;*.xlsm", , _
        "Шаг 1 из 2 — выберите файл ОТЧЁТА (Отчет по пакету актов ....xlsx)")
    If VarType(reportPath) = vbBoolean Then Exit Sub

    Dim masterPath As Variant
    masterPath = Application.GetOpenFilename( _
        "Excel Files (*.xlsx;*.xlsm),*.xlsx;*.xlsm", , _
        "Шаг 2 из 2 — выберите файл РЕЕСТРА (например, Проверка акт-нарядов 2026.xlsx)")
    If VarType(masterPath) = vbBoolean Then Exit Sub

    Dim reportWb As Workbook, masterWb As Workbook
    Dim wbLoop As Workbook
    Dim wasReportOpen As Boolean, wasMasterOpen As Boolean

    wasReportOpen = False
    For Each wbLoop In Workbooks
        If StrComp(wbLoop.FullName, CStr(reportPath), vbTextCompare) = 0 Then
            Set reportWb = wbLoop
            wasReportOpen = True
            Exit For
        End If
    Next wbLoop
    If Not wasReportOpen Then
        Application.ScreenUpdating = False
        Set reportWb = Workbooks.Open(CStr(reportPath))
    End If

    Dim srcWs As Worksheet
    On Error Resume Next
    Set srcWs = reportWb.Sheets("Реестр")
    On Error GoTo 0
    If srcWs Is Nothing Then
        MsgBox "В выбранном файле отчёта нет листа ""Реестр"".", vbExclamation
        If Not wasReportOpen Then reportWb.Close SaveChanges:=False
        Application.ScreenUpdating = True
        Exit Sub
    End If

    Dim lastRowSrc As Long
    lastRowSrc = srcWs.Cells(srcWs.Rows.Count, 1).End(xlUp).Row
    If lastRowSrc < 2 Then
        MsgBox "В листе ""Реестр"" нет строк для переноса.", vbExclamation
        If Not wasReportOpen Then reportWb.Close SaveChanges:=False
        Application.ScreenUpdating = True
        Exit Sub
    End If

    wasMasterOpen = False
    For Each wbLoop In Workbooks
        If StrComp(wbLoop.FullName, CStr(masterPath), vbTextCompare) = 0 Then
            Set masterWb = wbLoop
            wasMasterOpen = True
            Exit For
        End If
    Next wbLoop
    If Not wasMasterOpen Then
        Set masterWb = Workbooks.Open(CStr(masterPath))
    End If

    Dim destWs As Worksheet
    Set destWs = masterWb.Sheets(1)

    Dim lastRowDest As Long
    lastRowDest = destWs.Cells(destWs.Rows.Count, 1).End(xlUp).Row

    Dim overallNum As Long, perDateNum As Long
    Dim lastDate As String
    If lastRowDest >= 2 Then
        overallNum = CLng(Val(destWs.Cells(lastRowDest, 1).Value))
        perDateNum = CLng(Val(destWs.Cells(lastRowDest, 2).Value))
        lastDate = CStr(destWs.Cells(lastRowDest, 9).Value)
    Else
        overallNum = 0
        perDateNum = 0
        lastDate = ""
        lastRowDest = 1
    End If

    Dim colCount As Long
    colCount = srcWs.Cells(1, srcWs.Columns.Count).End(xlToLeft).Column

    Dim srcRow As Long, destRow As Long, c As Long
    Dim curDate As String
    destRow = lastRowDest + 1
    For srcRow = 2 To lastRowSrc
        curDate = CStr(srcWs.Cells(srcRow, 9).Value)
        overallNum = overallNum + 1
        If curDate = lastDate And curDate <> "" Then
            perDateNum = perDateNum + 1
        Else
            perDateNum = 1
            lastDate = curDate
        End If

        destWs.Cells(destRow, 1).Value = overallNum
        destWs.Cells(destRow, 2).Value = perDateNum
        For c = 3 To colCount
            destWs.Cells(destRow, c).Value = srcWs.Cells(srcRow, c).Value
        Next c
        destRow = destRow + 1
    Next srcRow

    masterWb.Save

    ' Отчёт-источник закрываем без сохранения — мы его только читали.
    If Not wasReportOpen Then reportWb.Close SaveChanges:=False
    Application.ScreenUpdating = True

    Dim addedCount As Long
    addedCount = lastRowSrc - 1

    Dim msg As String
    msg = "Готово: добавлено строк " & addedCount & " в файл реестра:" & vbCrLf & CStr(masterPath)
    If wasMasterOpen Then
        msg = msg & vbCrLf & vbCrLf & "(книга реестра была уже открыта — сохранена как есть)"
    Else
        masterWb.Close SaveChanges:=False
    End If
    MsgBox msg, vbInformation
End Sub
