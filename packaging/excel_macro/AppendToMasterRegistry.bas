Sub AppendToMasterRegistry()
    ' Кнопка живёт прямо в мастер-реестре (напр. "Проверка акт-нарядов
    ' 2026.xlsx") — ThisWorkbook и есть реестр, поэтому спрашиваем только
    ' файл-источник (свежий отчёт), а пишем сразу в эту же книгу.

    ' Отчёт приложение реально сохраняет на диск (не только открывает) —
    ' просто в малозаметную рабочую папку. Открываем диалог сразу там,
    ' чтобы не искать файл руками по всему компьютеру.
    Dim reportsFolder As String
    reportsFolder = Environ("LOCALAPPDATA") & "\AktNaryadVerifier\output"
    If Dir(reportsFolder, vbDirectory) <> "" Then
        On Error Resume Next
        ChDrive Left(reportsFolder, 1)
        ChDir reportsFolder
        On Error GoTo 0
    End If

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

    ' --- Лист "Реестр" источника -> первый лист этой книги ---
    Dim srcWsReg As Worksheet
    On Error Resume Next
    Set srcWsReg = srcWb.Sheets("Реестр")
    On Error GoTo 0

    Dim addedReg As Long
    addedReg = 0
    If Not srcWsReg Is Nothing Then
        addedReg = AppendRegistryRows(srcWsReg, ThisWorkbook.Sheets(1))
    End If

    ' --- Лист "Сводка" источника -> лист "Сводка" этой книги (создаём при
    ' первом переносе, дальше просто пополняем — с сохранением цветовой
    ' подсветки по каждой проверке) ---
    Dim srcWsSum As Worksheet
    On Error Resume Next
    Set srcWsSum = srcWb.Sheets("Сводка")
    On Error GoTo 0

    Dim addedSum As Long
    addedSum = 0
    If Not srcWsSum Is Nothing Then
        Dim destWsSum As Worksheet
        On Error Resume Next
        Set destWsSum = ThisWorkbook.Sheets("Сводка")
        On Error GoTo 0
        If destWsSum Is Nothing Then
            Set destWsSum = ThisWorkbook.Sheets.Add(After:=ThisWorkbook.Sheets(ThisWorkbook.Sheets.Count))
            destWsSum.Name = "Сводка"
        End If
        addedSum = AppendSummaryRows(srcWsSum, destWsSum)
    End If

    If Not wasSrcOpen Then srcWb.Close SaveChanges:=False
    Application.ScreenUpdating = True

    ThisWorkbook.Save

    MsgBox "Готово." & vbCrLf & _
        "Реестр: добавлено строк " & addedReg & "." & vbCrLf & _
        "Сводка: добавлено строк " & addedSum & ".", vbInformation
End Sub

Private Function AppendRegistryRows(srcWs As Worksheet, destWs As Worksheet) As Long
    Dim lastRowSrc As Long
    lastRowSrc = srcWs.Cells(srcWs.Rows.Count, 1).End(xlUp).Row
    If lastRowSrc < 2 Then
        AppendRegistryRows = 0
        Exit Function
    End If

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

    AppendRegistryRows = lastRowSrc - 1
End Function

Private Function AppendSummaryRows(srcWs As Worksheet, destWs As Worksheet) As Long
    Dim lastRowSrc As Long
    lastRowSrc = srcWs.Cells(srcWs.Rows.Count, 1).End(xlUp).Row
    If lastRowSrc < 2 Then
        AppendSummaryRows = 0
        Exit Function
    End If

    Dim colCount As Long
    colCount = srcWs.Cells(1, srcWs.Columns.Count).End(xlToLeft).Column

    Dim lastRowDest As Long
    lastRowDest = destWs.Cells(destWs.Rows.Count, 1).End(xlUp).Row

    ' Лист только что создан (пуст) — сначала копируем шапку с колонками.
    If destWs.Cells(1, 1).Value = "" Then
        srcWs.Range(srcWs.Cells(1, 1), srcWs.Cells(1, colCount)).Copy
        destWs.Cells(1, 1).PasteSpecial xlPasteAll
        Application.CutCopyMode = False
        lastRowDest = 1
    End If

    ' Копируем значения И форматирование (в т.ч. цветовую заливку по
    ' статусу проверки) одним диапазоном — не строка за строкой.
    Dim srcRange As Range
    Set srcRange = srcWs.Range(srcWs.Cells(2, 1), srcWs.Cells(lastRowSrc, colCount))
    srcRange.Copy
    destWs.Cells(lastRowDest + 1, 1).PasteSpecial xlPasteAll
    Application.CutCopyMode = False

    AppendSummaryRows = lastRowSrc - 1
End Function
