Sub AppendToMasterRegistry()
    ' Кнопка живёт прямо в мастер-реестре (напр. "Проверка акт-нарядов
    ' 2026.xlsx") — ThisWorkbook и есть реестр, поэтому спрашиваем только
    ' файл-источник (свежий отчёт), а пишем сразу в тот же лист, где кнопка.
    Dim reportPath As Variant
    reportPath = Application.GetOpenFilename( _
        "Excel Files (*.xlsx;*.xlsm),*.xlsx;*.xlsm", , _
        "Выберите файл отчёта (Отчет по пакету актов ....xlsx)")
    If VarType(reportPath) = vbBoolean Then Exit Sub

    Dim srcWb As Workbook
    Dim wbLoop As Workbook
    Dim wasSrcOpen As Boolean
    wasSrcOpen = False
    For Each wbLoop In Workbooks
        If StrComp(wbLoop.FullName, CStr(reportPath), vbTextCompare) = 0 Then
            Set srcWb = wbLoop
            wasSrcOpen = True
            Exit For
        End If
    Next wbLoop
    If Not wasSrcOpen Then
        Application.ScreenUpdating = False
        Set srcWb = Workbooks.Open(CStr(reportPath))
    End If

    Dim srcWs As Worksheet
    On Error Resume Next
    Set srcWs = srcWb.Sheets("Реестр")
    On Error GoTo 0
    If srcWs Is Nothing Then
        MsgBox "В выбранном файле отчёта нет листа ""Реестр"".", vbExclamation
        If Not wasSrcOpen Then srcWb.Close SaveChanges:=False
        Application.ScreenUpdating = True
        Exit Sub
    End If

    Dim lastRowSrc As Long
    lastRowSrc = srcWs.Cells(srcWs.Rows.Count, 1).End(xlUp).Row
    If lastRowSrc < 2 Then
        MsgBox "В листе ""Реестр"" нет строк для переноса.", vbExclamation
        If Not wasSrcOpen Then srcWb.Close SaveChanges:=False
        Application.ScreenUpdating = True
        Exit Sub
    End If

    Dim destWs As Worksheet
    Set destWs = ThisWorkbook.Sheets(1)

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

    If Not wasSrcOpen Then srcWb.Close SaveChanges:=False
    Application.ScreenUpdating = True

    ThisWorkbook.Save

    Dim addedCount As Long
    addedCount = lastRowSrc - 1
    MsgBox "Готово: добавлено строк " & addedCount & ".", vbInformation
End Sub
