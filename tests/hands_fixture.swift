import Cocoa

final class Row: NSTextField {
    var reveal: (() -> Void)?
    override func accessibilityActionNames() -> [NSAccessibility.Action] { super.accessibilityActionNames() + [NSAccessibility.Action(rawValue:"AXScrollToVisible")] }
    override func accessibilityPerformAction(_ action: NSAccessibility.Action) { if action.rawValue == "AXScrollToVisible" { reveal?() } else { super.accessibilityPerformAction(action) } }
}
final class Scroller: NSScrollView {
    override func accessibilityActionNames() -> [NSAccessibility.Action] { super.accessibilityActionNames() + [NSAccessibility.Action(rawValue:"AXScrollDownByPage"),NSAccessibility.Action(rawValue:"AXScrollUpByPage")] }
    override func accessibilityPerformAction(_ action: NSAccessibility.Action) {
        if action.rawValue == "AXScrollDownByPage" { _ = move(1) }
        else if action.rawValue == "AXScrollUpByPage" { _ = move(-1) }
        else { super.accessibilityPerformAction(action) }
    }
    func move(_ direction: CGFloat) -> Bool {
        let old = contentView.bounds.origin.y
        let next = max(0,min((documentView?.bounds.height ?? 0) - contentView.bounds.height, old + direction * contentView.bounds.height))
        contentView.scroll(to: NSPoint(x:0,y:next)); reflectScrolledClipView(contentView)
        return next != old
    }
}
final class Document: NSView { override var isFlipped: Bool { true } }
final class Fixture: NSObject, NSApplicationDelegate {
    var window: NSWindow!, sheet: NSWindow?, field: NSTextField!, secure: NSSecureTextField!, check: NSButton!, scroll: Scroller!
    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let appMenu = NSMenuItem(title:"Hands Fixture",action:nil,keyEquivalent:""); appMenu.submenu = NSMenu(); menu.addItem(appMenu)
        let file = NSMenuItem(title:"File",action:nil,keyEquivalent:""), submenu = NSMenu()
        let export = NSMenuItem(title:"Export To",action:nil,keyEquivalent:""), formats = NSMenu()
        let pdf = NSMenuItem(title:"PDF…",action:#selector(pdfAction),keyEquivalent:""); pdf.target = self
        formats.addItem(pdf); export.submenu = formats; submenu.addItem(export); file.submenu = submenu; menu.addItem(file); NSApp.mainMenu = menu
        window = NSWindow(contentRect:NSRect(x:12,y:12,width:340,height:320),styleMask:[.titled],backing:.buffered,defer:false)
        window.title = "Hands Fixture"; window.isReleasedWhenClosed = false; window.animationBehavior = .none
        let root = NSView(frame:NSRect(x:0,y:0,width:340,height:320)); window.contentView = root
        for (i,title) in ["Export","Send","Delete draft","Duplicate"].enumerated() {
            let b = NSButton(title:title,target:self,action:i == 0 ? #selector(exportAction) : #selector(buttonAction(_:)))
            b.frame = NSRect(x:8 + i * 82,y:280,width:80,height:28); b.setAccessibilityLabel(title); root.addSubview(b)
        }
        check = NSButton(checkboxWithTitle:"Enabled",target:self,action:#selector(buttonAction(_:))); check.frame = NSRect(x:8,y:248,width:100,height:24); root.addSubview(check)
        field = NSTextField(frame:NSRect(x:110,y:248,width:220,height:24)); field.setAccessibilityLabel("Name"); field.stringValue = "4111 1111 1111 1111"; root.addSubview(field)
        secure = NSSecureTextField(frame:NSRect(x:110,y:214,width:220,height:24)); secure.setAccessibilityLabel("Password"); secure.stringValue = "never-print-me"; root.addSubview(secure)
        scroll = Scroller(frame:NSRect(x:8,y:8,width:324,height:198)); scroll.hasVerticalScroller = true
        let document = Document(frame:NSRect(x:0,y:0,width:300,height:4800)); scroll.documentView = document
        for i in 1...200 {
            let row = Row(labelWithString:"Row \(i)"); row.frame = NSRect(x:8,y:CGFloat(i-1) * 24,width:260,height:24)
            row.reveal = { [weak row, weak scroll] in if let row, let scroll { scroll.contentView.scroll(to:NSPoint(x:0,y:max(0,min(4602,row.frame.minY)))); scroll.reflectScrolledClipView(scroll.contentView) } }
            document.addSubview(row)
        }
        root.addSubview(scroll); scroll.contentView.scroll(to:NSPoint(x:0,y:0)); scroll.reflectScrolledClipView(scroll.contentView)
        window.orderFrontRegardless()
        DispatchQueue.main.async {
            precondition(self.window.isVisible && self.window.accessibilityRole() == .window && !NSApp.isActive)
            try? String(ProcessInfo.processInfo.processIdentifier).write(toFile:CommandLine.arguments[1] + "/fixture-ready",atomically:true,encoding:.utf8)
        }
        // Fixture control via a scratch file; no focus, mouse, Apple Events or personal state.
        Timer.scheduledTimer(withTimeInterval:0.02,repeats:true) { [weak self] _ in
            let path = CommandLine.arguments[1] + "/fixture-command"
            guard let command = try? String(contentsOfFile:path,encoding:.utf8) else { return }
            defer { DispatchQueue.main.async { try? FileManager.default.removeItem(atPath:path) } }
            if command == "close-sheet" { self?.closeSheet() }
            if command == "stale" { self?.window.title = "Hands Fixture Changed" }
            if command == "duplicate" {
                let b = NSButton(title:"Export",target:self,action:#selector(Fixture.exportAction)); b.frame = NSRect(x:8,y:214,width:80,height:24); self?.window.contentView?.addSubview(b)
            }
            if command == "long-text", let root = self?.window.contentView {
                root.subviews.forEach { $0.removeFromSuperview() }
                let editor = NSTextView(frame: root.bounds)
                editor.string = String(repeating: "Document paragraph with unfamiliar words. ", count: 300) + "DOCUMENT END"
                root.addSubview(editor)
            }
            if command == "rich-table", let root = self?.window.contentView {
                root.subviews.forEach { $0.removeFromSuperview() }
                let editor = NSTextView(frame:root.bounds), table = NSTextTable(), text = NSMutableAttributedString(string:"")
                table.numberOfColumns = 2
                for (row,cells) in [["Explain the observed relationship:",""],["A second prompt must remain.",""]].enumerated() {
                    for (column,cell) in cells.enumerated() {
                        let block = NSTextTableBlock(table:table,startingRow:row,rowSpan:1,startingColumn:column,columnSpan:1)
                        let paragraph = NSMutableParagraphStyle(); paragraph.textBlocks = [block]
                        text.append(NSAttributedString(string:cell + "\n",attributes:[.paragraphStyle:paragraph]))
                    }
                }
                editor.textStorage?.setAttributedString(text); editor.setAccessibilityLabel("Document"); root.addSubview(editor)
            }
            if command == "stop" { NSApp.terminate(nil) }
        }
    }
    @objc func exportAction() {
        let sheet = NSWindow(contentRect:NSRect(x:0,y:0,width:220,height:90),styleMask:[.titled],backing:.buffered,defer:false)
        sheet.animationBehavior = .none
        sheet.title = "Export Your Document"
        let title = NSTextField(labelWithString:"Export Your Document"); title.frame = NSRect(x:8,y:48,width:200,height:24); sheet.contentView?.addSubview(title)
        let b = NSButton(title:"Save",target:self,action:#selector(saveAction)); b.frame = NSRect(x:8,y:8,width:90,height:28); sheet.contentView?.addSubview(b)
        self.sheet = sheet; window.beginSheet(sheet)
    }
    func closeSheet() { if let sheet { window.endSheet(sheet); sheet.orderOut(nil); self.sheet = nil } }
    @objc func saveAction() { record("save"); closeSheet() }
    @objc func pdfAction() { record("pdf"); window.title = "Hands Fixture PDF" }
    @objc func buttonAction(_ sender: NSButton) {
        record(sender.title)
        if sender !== check { sender.title += " clicked" }
    }
    func record(_ text: String) { try? text.write(toFile:CommandLine.arguments[1] + "/fixture-result",atomically:true,encoding:.utf8) }
}
let app = NSApplication.shared; app.setActivationPolicy(.accessory)
let fixture = Fixture(); app.delegate = fixture; app.run()
