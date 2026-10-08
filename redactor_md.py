"""Редактор MD — оконный редактор Markdown с живым просмотром (PySide6)."""

import re
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import (
    QAction, QColor, QFont, QKeySequence, QPalette, QSyntaxHighlighter,
    QTextCharFormat, QTextCursor, QTextDocument, QTextFormat,
    QTextTable,
)
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QInputDialog, QLabel, QMainWindow, QMessageBox,
    QPlainTextEdit, QSplitter, QStyleFactory, QTextBrowser,
)

APP = "Редактор MD"
UNTITLED = "без названия.md"
FILTER = "Markdown (*.md *.markdown *.txt);;Все файлы (*)"
LIST_RE = re.compile(r"^(\s*)([-*+] \[[ xX]\] |[-*+] |(\d+)\. |> )(.*)$")
WORD_RE = re.compile(r"\w+")
PREFIX_RE = re.compile(r"^(#{1,6} |> |[-*+] \[[ xX]\] |[-*+] |\d+\. )")
WELCOME = (
    "# Добро пожаловать\n\n"
    "Это **редактор Markdown**. Слева — текст, справа — просмотр.\n\n"
    "- `Ctrl+O` — открыть, `Ctrl+S` — сохранить\n"
    "- Файл можно перетащить в окно\n"
)


class Highlighter(QSyntaxHighlighter):
    """Подсветка разметки Markdown в редакторе."""

    def __init__(self, doc, dark):
        super().__init__(doc)
        self.set_dark(dark)

    def set_dark(self, dark):
        def fmt(color, bold=False, italic=False, mono_bg=None):
            f = QTextCharFormat()
            if color:
                f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(QFont.Bold)
            if italic:
                f.setFontItalic(True)
            if mono_bg:
                f.setBackground(QColor(mono_bg))
            return f

        c = {
            "head": "#79b8ff" if dark else "#0550ae",
            "mark": "#9aa1ab" if dark else "#6a737d",
            "code": "#ffab70" if dark else "#953800",
            "code_bg": "#262a33" if dark else "#f0f2f5",
            "link": "#85e89d" if dark else "#116329",
            "quote": "#9aa1ab" if dark else "#57606a",
        }
        self.rules = [
            (re.compile(r"^#{1,6} .*$"), fmt(c["head"], bold=True)),
            (re.compile(r"\*\*[^*\n]+\*\*|__[^_\n]+__"), fmt("", bold=True)),
            (re.compile(r"(?<![*\w])\*[^*\n]+\*(?!\*)|(?<![_\w])_[^_\n]+_(?!_)"), fmt("", italic=True)),
            (re.compile(r"~~[^~\n]+~~"), fmt(c["mark"])),
            (re.compile(r"^\s*([-*+]( \[[ xX]\])?|\d+\.) "), fmt(c["mark"], bold=True)),
            (re.compile(r"^>.*$"), fmt(c["quote"], italic=True)),
            (re.compile(r"!?\[[^\]\n]*\]\([^)\n]*\)"), fmt(c["link"])),
            (re.compile(r"^(-{3,}|\*{3,})\s*$"), fmt(c["mark"])),
            (re.compile(r"`[^`\n]+`"), fmt(c["code"], mono_bg=c["code_bg"])),
        ]
        self.fence = fmt(c["code"], mono_bg=c["code_bg"])
        self.rehighlight()

    def highlightBlock(self, text):
        in_fence = self.previousBlockState() == 1
        if text.lstrip().startswith("```"):
            self.setFormat(0, len(text), self.fence)
            self.setCurrentBlockState(0 if in_fence else 1)
            return
        if in_fence:
            self.setFormat(0, len(text), self.fence)
            self.setCurrentBlockState(1)
            return
        self.setCurrentBlockState(0)
        for rx, f in self.rules:
            for m in rx.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), f)


class Editor(QPlainTextEdit):
    """Текстовое поле: продолжение списков по Enter, отступы по Tab."""

    def keyPressEvent(self, e):
        key, mods = e.key(), e.modifiers()
        cur = self.textCursor()
        if key in (Qt.Key_Tab, Qt.Key_Backtab):
            if cur.hasSelection() or key == Qt.Key_Backtab:
                self.window().indent_lines(outdent=key == Qt.Key_Backtab)
            else:
                cur.insertText("    ")
            return
        if key in (Qt.Key_Return, Qt.Key_Enter) and not mods and not cur.hasSelection():
            line = cur.block().text()[: cur.positionInBlock()]
            m = LIST_RE.match(line)
            if m:
                indent, marker, num, rest = m.groups()
                if not rest.strip():  # пустой пункт — выходим из списка
                    cur.movePosition(QTextCursor.StartOfBlock, QTextCursor.KeepAnchor)
                    cur.insertText("")
                    return
                if num:
                    marker = f"{int(num) + 1}. "
                elif "[" in marker:
                    marker = re.sub(r"\[[xX]\]", "[ ]", marker)
                cur.insertText("\n" + indent + marker)
                self.ensureCursorVisible()
                return
        super().keyPressEvent(e)

    # Перетаскивание файлов обрабатывает окно, а не поле ввода
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.ignore()
        else:
            super().dragEnterEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            e.ignore()
        else:
            super().dropEvent(e)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("redactorMD", "redactorMD")
        self.path = None
        self.mode = "split"

        self.editor = Editor()
        self.editor.setFont(QFont("Consolas", 11) if sys.platform == "win32" else QFont("Monospace", 11))
        self.editor.setTabStopDistance(self.editor.fontMetrics().horizontalAdvance(" ") * 4)
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(True)
        self.preview.document().setDocumentMargin(16)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.editor)
        self.splitter.addWidget(self.preview)
        self.setCentralWidget(self.splitter)

        self.stats = QLabel()
        self.statusBar().addPermanentWidget(self.stats)

        self.timer = QTimer(self, singleShot=True, interval=150, timeout=self.render)
        self.editor.textChanged.connect(self.timer.start)
        self.editor.document().modificationChanged.connect(self.update_title)
        self.editor.verticalScrollBar().valueChanged.connect(self.sync_scroll)

        self.dark = self.settings.value("dark", False, type=bool)
        self.highlighter = Highlighter(self.editor.document(), self.dark)
        self.build_actions()
        self.apply_theme()
        self.set_mode(self.settings.value("mode", "split"))
        self.setAcceptDrops(True)
        self.resize(1100, 700)
        if geo := self.settings.value("geometry"):
            self.restoreGeometry(geo)

    # ---------- Меню и панель ----------
    def build_actions(self):
        def act(text, slot, shortcut=None, tip=None):
            a = QAction(text, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            a.setToolTip(f"{tip or text} ({QKeySequence(shortcut).toString()})" if shortcut else (tip or text))
            return a

        menu = self.menuBar()
        tb = self.addToolBar("Панель")
        tb.setMovable(False)
        tb.setObjectName("toolbar")

        f = menu.addMenu("&Файл")
        file_acts = [
            act("Новый", self.new_file, QKeySequence.New),
            act("Открыть…", self.open_file, QKeySequence.Open),
            act("Сохранить", self.save, QKeySequence.Save),
            act("Сохранить как…", self.save_as, "Ctrl+Shift+S"),
        ]
        f.addActions(file_acts)
        self.recent_menu = f.addMenu("Недавние")
        self.update_recent()
        f.addSeparator()
        f.addAction(act("Экспорт в HTML…", self.export_html))
        f.addSeparator()
        f.addAction(act("Выход", self.close, "Ctrl+Q"))
        tb.addActions(file_acts)
        tb.addSeparator()

        e = menu.addMenu("&Правка")
        e.addAction(act("Отменить", self.editor.undo, QKeySequence.Undo))
        e.addAction(act("Повторить", self.editor.redo, QKeySequence.Redo))
        e.addSeparator()
        e.addAction(act("Найти…", self.find, QKeySequence.Find))
        e.addAction(act("Найти далее", lambda: self.find(again=True), QKeySequence.FindNext))
        e.addAction(act("Заменить…", self.replace, QKeySequence.Replace))

        fm = menu.addMenu("Ф&ормат")
        fmt_acts = [
            act("Ж", lambda: self.wrap("**"), "Ctrl+B", "Жирный"),
            act("К", lambda: self.wrap("*"), "Ctrl+I", "Курсив"),
            act("З", lambda: self.wrap("~~"), None, "Зачёркнутый"),
            act("H1", lambda: self.prefix("# "), "Ctrl+1", "Заголовок 1"),
            act("H2", lambda: self.prefix("## "), "Ctrl+2", "Заголовок 2"),
            act("H3", lambda: self.prefix("### "), "Ctrl+3", "Заголовок 3"),
            act("•", lambda: self.prefix("- "), None, "Маркированный список"),
            act("1.", self.numbered, None, "Нумерованный список"),
            act("☐", lambda: self.prefix("- [ ] "), None, "Чек-лист"),
            act("❝", lambda: self.prefix("> "), None, "Цитата"),
            act("</>", self.code, "Ctrl+`", "Код"),
            act("🔗", self.link, "Ctrl+K", "Ссылка"),
            act("▦", lambda: self.block("| Столбец 1 | Столбец 2 |\n|-----------|-----------|\n| Ячейка    | Ячейка    |"), None, "Таблица"),
            act("―", lambda: self.block("---"), None, "Горизонтальная линия"),
        ]
        bold_font = QFont(); bold_font.setBold(True)
        italic_font = QFont(); italic_font.setItalic(True)
        strike_font = QFont(); strike_font.setStrikeOut(True)
        for a, fnt in zip(fmt_acts, (bold_font, italic_font, strike_font)):
            a.setFont(fnt)
        for a in fmt_acts:
            fm.addAction(a.toolTip().split(" (")[0]).triggered.connect(a.trigger)
        tb.addActions(fmt_acts)
        tb.addSeparator()

        v = menu.addMenu("&Вид")
        self.mode_acts = {}
        for key, text, sc in (("edit", "✎", "Ctrl+Alt+1"), ("split", "◫", "Ctrl+Alt+2"), ("view", "👁", "Ctrl+Alt+3")):
            tip = {"edit": "Только редактор", "split": "Редактор и просмотр", "view": "Только просмотр"}[key]
            a = act(text, lambda _=False, k=key: self.set_mode(k), sc, tip)
            a.setCheckable(True)
            self.mode_acts[key] = a
            v.addAction(tip).triggered.connect(a.trigger)
            tb.addAction(a)
        v.addSeparator()
        theme = act("🌓", self.toggle_theme, "Ctrl+Alt+T", "Тёмная тема")
        v.addAction("Тёмная тема").triggered.connect(theme.trigger)
        v.addAction(act("Крупнее", lambda: self.zoom(1), QKeySequence.ZoomIn))
        v.addAction(act("Мельче", lambda: self.zoom(-1), QKeySequence.ZoomOut))
        tb.addAction(theme)

    # ---------- Документ ----------
    def render(self):
        bar = self.preview.verticalScrollBar()
        pos = bar.value()
        text = self.editor.toPlainText()
        self.preview.setMarkdown(text)
        self.style_preview()
        bar.setValue(pos)
        self.stats.setText(
            f"Слов: {len(WORD_RE.findall(text))} · Символов: {len(text)} · Строк: {self.editor.blockCount()}"
        )

    def style_preview(self):
        """Отступы между абзацами и рамки таблиц — у Qt по умолчанию всё слишком плотно."""
        doc = self.preview.document()
        cur = QTextCursor(doc)
        cur.beginEditBlock()
        block = doc.begin()
        while block.isValid():
            fmt = block.blockFormat()
            level = fmt.headingLevel()
            c = QTextCursor(block)
            if not block.textList() and not c.currentTable():
                fmt.setTopMargin(14 if level else fmt.topMargin())
                fmt.setBottomMargin(8 if level else 10)
            else:
                fmt.setBottomMargin(3)
            fmt.setLineHeight(130, 1)  # 1 = ProportionalHeight, межстрочный 130%
            if fmt.hasProperty(QTextFormat.BlockCodeFence):  # блок кода — с фоном
                fmt.setBackground(QColor("#262a33" if self.dark else "#f0f2f5"))
                fmt.setTopMargin(0)
                fmt.setBottomMargin(0)
            elif fmt.hasProperty(QTextFormat.BlockQuoteLevel):  # цитата — приглушённым цветом
                cf = QTextCharFormat()
                cf.setForeground(QColor("#9aa1ab" if self.dark else "#57606a"))
                c.select(QTextCursor.BlockUnderCursor)
                c.mergeCharFormat(cf)
                c = QTextCursor(block)
            c.setBlockFormat(fmt)
            block = block.next()
        for frame in doc.rootFrame().childFrames():
            if isinstance(frame, QTextTable):
                tf = frame.format()
                tf.setCellPadding(6)
                tf.setCellSpacing(0)
                tf.setBorder(1)
                tf.setBorderCollapse(True)
                tf.setBottomMargin(10)
                frame.setFormat(tf)
        cur.endEditBlock()

    def sync_scroll(self):
        if self.mode != "split":
            return
        src, dst = self.editor.verticalScrollBar(), self.preview.verticalScrollBar()
        if src.maximum():
            dst.setValue(round(src.value() / src.maximum() * dst.maximum()))

    def name(self):
        return self.path.name if self.path else UNTITLED

    def update_title(self):
        mark = " •" if self.editor.document().isModified() else ""
        self.setWindowTitle(f"{self.name()}{mark} — {APP}")

    def load(self, text, path=None):
        self.path = Path(path) if path else None
        self.editor.setPlainText(text)
        self.editor.document().setModified(False)
        if self.path:
            self.preview.setSearchPaths([str(self.path.parent)])  # для картинок с относительными путями
            self.add_recent(self.path)
        self.render()
        self.update_title()

    def confirm_discard(self):
        if not self.editor.document().isModified():
            return True
        r = QMessageBox.question(
            self, APP, f"Сохранить изменения в «{self.name()}»?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
        )
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    def new_file(self):
        if self.confirm_discard():
            self.load("")

    def open_file(self, path=None):
        if not self.confirm_discard():
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Открыть", self.last_dir(), FILTER)
            if not path:
                return
        try:
            raw = Path(path).read_bytes()
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("cp1251")  # старые файлы Windows
        except OSError as err:
            QMessageBox.warning(self, APP, f"Не удалось открыть файл:\n{err}")
            return
        self.load(text.replace("\r\n", "\n"), path)

    def save(self):
        if not self.path:
            return self.save_as()
        try:
            self.path.write_text(self.editor.toPlainText(), encoding="utf-8")
        except OSError as err:
            QMessageBox.warning(self, APP, f"Не удалось сохранить файл:\n{err}")
            return False
        self.editor.document().setModified(False)
        self.statusBar().showMessage("Сохранено", 2000)
        return True

    def save_as(self):
        start = str(Path(self.last_dir()) / self.name())
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить как", start, FILTER)
        if not path:
            return False
        if not Path(path).suffix:
            path += ".md"
        self.path = Path(path)
        self.add_recent(self.path)
        ok = self.save()
        self.update_title()
        return ok

    def export_html(self):
        start = str(Path(self.last_dir()) / (Path(self.name()).stem + ".html"))
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт в HTML", start, "HTML (*.html)")
        if not path:
            return
        doc = QTextDocument()
        doc.setMarkdown(self.editor.toPlainText())
        doc.setMetaInformation(QTextDocument.DocumentTitle, Path(self.name()).stem)
        Path(path).write_text(doc.toHtml(), encoding="utf-8")
        self.statusBar().showMessage(f"Экспортировано: {path}", 3000)

    def last_dir(self):
        if self.path:
            return str(self.path.parent)
        return self.settings.value("last_dir", str(Path.home()))

    def add_recent(self, path):
        self.settings.setValue("last_dir", str(path.parent))
        items = [p for p in self.settings.value("recent", [], type=list) if p != str(path)]
        self.settings.setValue("recent", [str(path)] + items[:9])
        self.update_recent()

    def update_recent(self):
        self.recent_menu.clear()
        items = self.settings.value("recent", [], type=list)
        for p in items:
            self.recent_menu.addAction(p).triggered.connect(lambda _=False, p=p: self.open_file(p))
        self.recent_menu.setEnabled(bool(items))

    # ---------- Форматирование ----------
    def wrap(self, before, after=None, placeholder="текст"):
        after = before if after is None else after
        cur = self.editor.textCursor()
        sel = cur.selectedText().replace(" ", "\n") or placeholder
        doc_text = self.editor.toPlainText()
        s, e = cur.selectionStart(), cur.selectionEnd()
        # повторное нажатие снимает форматирование
        if doc_text[s - len(before):s] == before and doc_text[e:e + len(after)] == after and cur.hasSelection():
            cur.setPosition(s - len(before))
            cur.setPosition(e + len(after), QTextCursor.KeepAnchor)
            cur.insertText(sel)
            cur.setPosition(s - len(before))
            cur.setPosition(s - len(before) + len(sel), QTextCursor.KeepAnchor)
        else:
            cur.insertText(before + sel + after)
            cur.setPosition(s + len(before))
            cur.setPosition(s + len(before) + len(sel), QTextCursor.KeepAnchor)
        self.editor.setTextCursor(cur)
        self.editor.setFocus()

    def map_lines(self, fn):
        """Применяет fn(строка, индекс) к каждой выделенной строке."""
        cur = self.editor.textCursor()
        s, e = cur.selectionStart(), cur.selectionEnd()
        cur.setPosition(s)
        cur.movePosition(QTextCursor.StartOfBlock)
        start = cur.position()
        cur.setPosition(e, QTextCursor.KeepAnchor)
        if cur.hasSelection() and cur.positionInBlock() == 0 and e > s:
            cur.movePosition(QTextCursor.PreviousCharacter, QTextCursor.KeepAnchor)
        cur.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
        lines = cur.selectedText().split(" ")
        out = "\n".join(fn(l, i) for i, l in enumerate(lines))
        cur.insertText(out)
        cur.setPosition(start)
        cur.setPosition(start + len(out), QTextCursor.KeepAnchor)
        self.editor.setTextCursor(cur)
        self.editor.setFocus()

    def prefix(self, p):
        self.map_lines(lambda l, _: l[len(p):] if l.startswith(p) else p + PREFIX_RE.sub("", l))

    def numbered(self):
        self.map_lines(lambda l, i: re.sub(r"^\d+\. ", "", l) if re.match(r"^\d+\. ", l)
                       else f"{i + 1}. {PREFIX_RE.sub('', l)}")

    def indent_lines(self, outdent=False):
        self.map_lines(lambda l, _: re.sub(r"^( {1,4}|\t)", "", l) if outdent else "    " + l)

    def code(self):
        sel = self.editor.textCursor().selectedText()
        if " " in sel:
            self.wrap("```\n", "\n```", "")
        else:
            self.wrap("`", "`", "код")

    def link(self):
        cur = self.editor.textCursor()
        text = cur.selectedText() or "текст"
        s = cur.selectionStart()
        cur.insertText(f"[{text}](https://)")
        cur.setPosition(s + len(text) + 3)
        cur.setPosition(s + len(text) + 11, QTextCursor.KeepAnchor)
        self.editor.setTextCursor(cur)
        self.editor.setFocus()

    def block(self, text):
        cur = self.editor.textCursor()
        cur.clearSelection()
        before = self.editor.toPlainText()[:cur.position()]
        if not before or before.endswith("\n\n"):
            pre = ""
        elif before.endswith("\n"):
            pre = "\n"
        else:
            pre = "\n\n"
        cur.insertText(pre + text + "\n")
        self.editor.setTextCursor(cur)
        self.editor.setFocus()

    # ---------- Поиск ----------
    def find(self, again=False):
        if not again or not getattr(self, "needle", ""):
            sel = self.editor.textCursor().selectedText()
            needle, ok = QInputDialog.getText(self, "Найти", "Текст:", text=sel or getattr(self, "needle", ""))
            if not ok or not needle:
                return
            self.needle = needle
        if not self.editor.find(self.needle):
            self.editor.moveCursor(QTextCursor.Start)  # с начала документа
            if not self.editor.find(self.needle):
                self.statusBar().showMessage("Не найдено", 2000)

    def replace(self):
        needle, ok = QInputDialog.getText(self, "Заменить", "Найти:", text=self.editor.textCursor().selectedText())
        if not ok or not needle:
            return
        repl, ok = QInputDialog.getText(self, "Заменить", f"Заменить «{needle}» на:")
        if not ok:
            return
        text = self.editor.toPlainText()
        n = text.count(needle)
        if n:
            cur = self.editor.textCursor()
            cur.select(QTextCursor.Document)
            cur.insertText(text.replace(needle, repl))  # одно действие — одна отмена
        self.statusBar().showMessage(f"Заменено: {n}", 3000)

    # ---------- Вид ----------
    def set_mode(self, mode):
        self.mode = mode if mode in ("edit", "split", "view") else "split"
        self.editor.setVisible(self.mode != "view")
        self.preview.setVisible(self.mode != "edit")
        for k, a in self.mode_acts.items():
            a.setChecked(k == self.mode)
        self.settings.setValue("mode", self.mode)

    def toggle_theme(self):
        self.dark = not self.dark
        self.settings.setValue("dark", self.dark)
        self.apply_theme()

    def apply_theme(self):
        app = QApplication.instance()
        app.setStyle(QStyleFactory.create("Fusion"))
        pal = QPalette()
        if self.dark:
            for role, color in (
                (QPalette.Window, "#1f2229"), (QPalette.WindowText, "#e6e8eb"),
                (QPalette.Base, "#16181d"), (QPalette.AlternateBase, "#1f2229"),
                (QPalette.Text, "#e6e8eb"), (QPalette.Button, "#262a33"),
                (QPalette.ButtonText, "#e6e8eb"), (QPalette.Highlight, "#2f6feb"),
                (QPalette.HighlightedText, "#ffffff"), (QPalette.ToolTipBase, "#262a33"),
                (QPalette.ToolTipText, "#e6e8eb"), (QPalette.Link, "#6ea8fe"),
                (QPalette.PlaceholderText, "#9aa1ab"),
            ):
                pal.setColor(role, QColor(color))
        else:
            pal = app.style().standardPalette()
        app.setPalette(pal)
        self.highlighter.set_dark(self.dark)
        self.render()

    def zoom(self, step):
        self.editor.zoomIn(step)
        self.preview.zoomIn(step)

    # ---------- События окна ----------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = [u for u in e.mimeData().urls() if u.isLocalFile()]
        if urls:
            self.open_file(urls[0].toLocalFile())

    def closeEvent(self, e):
        if self.confirm_discard():
            self.settings.setValue("geometry", self.saveGeometry())
            e.accept()
        else:
            e.ignore()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP)
    win = MainWindow()
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_file():
        win.open_file(sys.argv[1])
    else:
        win.load(WELCOME)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
