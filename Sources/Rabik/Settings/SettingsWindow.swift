// The Settings window. Part of the Rabik target: Sources/Rabik, built as one module (build.sh).
import Cocoa
import Carbon
import AVFoundation
import Speech
import WebKit
import ScreenCaptureKit
import Vision
import PDFKit
import QuickLookThumbnailing
import UniformTypeIdentifiers
import EventKit
import CoreAudio
import AudioToolbox

final class SettingsWindow: NSObject, WKScriptMessageHandler, WKNavigationDelegate, NSWindowDelegate {
    var win: NSWindow?, web: WKWebView?
    var feedbackJob = 0, feedbackURL: URL?

    var tab = "", timer: Timer?   // tab: shown once the page loads
    var pending: [(String, Any)] = []   // page calls waiting for it to load: a memory item, a meeting or a person to show

    func reveal(_ item: [String: Any]) { open(tab: "memory", then: "reveal", item) }
    func open(tab t: String, then call: String, _ value: Any) {   // a tab, then one thing on it (a source chip's meeting or person)
        if win == nil { pending.append((call, value)); open(tab: t) } else { open(tab: t); send(call, value) }
    }

    func open(tab t: String = "") {
        NSApp.activate(ignoringOtherApps: true)
        if let w = win { w.makeKeyAndOrderFront(nil); push(); refresh(); if !t.isEmpty { js("st.tab('\(t)')") }; return }
        tab = t
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 780, height: 560),
                         styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView], backing: .buffered, defer: false)
        applySharing(w)
        w.titlebarAppearsTransparent = true; w.titleVisibility = .hidden; w.title = "Rabik Settings"
        w.isReleasedWhenClosed = false; w.delegate = self
        w.contentMinSize = NSSize(width: 700, height: 460); w.contentMaxSize = NSSize(width: 1000, height: 820)   // wider only spreads the page into empty space
        w.collectionBehavior.insert(.fullScreenNone)   // the green button zooms up to the max size
        let bg = NSVisualEffectView(frame: w.contentRect(forFrameRect: w.frame))
        bg.material = .underWindowBackground; bg.blendingMode = .behindWindow; bg.state = .active
        let cfg = WKWebViewConfiguration()
        cfg.userContentController.add(self, name: "st")
        let v = WKWebView(frame: bg.bounds, configuration: cfg)
        v.autoresizingMask = [.width, .height]; v.setValue(false, forKey: "drawsBackground"); v.navigationDelegate = self
        loadPage(v, "settings.html")
        let bar = TitleBar(frame: NSRect(x: 0, y: bg.bounds.height - 28, width: bg.bounds.width, height: 28)); bar.autoresizingMask = [.width, .minYMargin]
        bg.addSubview(v); bg.addSubview(bar); w.contentView = bg
        win = w; web = v
        w.center(); w.setFrameUsingName("RabikSettings"); w.setFrameAutosaveName("RabikSettings")
        let saved = w.contentRect(forFrameRect: w.frame).size   // a frame saved before the max size existed (or full screen) shrinks to fit
        if saved.width > w.contentMaxSize.width || saved.height > w.contentMaxSize.height {
            w.setContentSize(NSSize(width: min(saved.width, w.contentMaxSize.width), height: min(saved.height, w.contentMaxSize.height))); w.center()
        }
        w.makeKeyAndOrderFront(nil)
        Onboarding.connectors { [weak self] c in self?.send("connectors", c) }
        timer = Timer.scheduledTimer(withTimeInterval: 1.5, repeats: true) { [weak self] _ in   // System Settings changes them behind our back
            self?.send("agents", ["count": agentsUI.count])   // the live count beside Settings
            DispatchQueue.global().async { self?.send("perms", Onboarding.perms()); self?.send("mics", microphoneChoices()); self?.send("globe", globeKeyTaken()) }
        }
    }

    func webView(_ v: WKWebView, decidePolicyFor a: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        decisionHandler(LocalPageOnly.allows(a) ? .allow : .cancel)   // its own page, nothing else (LocalPageOnly)
    }

    func webView(_ v: WKWebView, didFinish n: WKNavigation!) { push(); refresh(); DispatchQueue.global().async { [weak self] in self?.send("perms", Onboarding.perms()) }; if !tab.isEmpty { js("st.tab('\(tab)')"); tab = "" }; for (call, value) in pending { send(call, value) }; pending = [] }

    func send(_ call: String, _ v: Any) {
        DispatchQueue.main.async { [weak self] in callJS(self?.web, "st." + call, [v]) }
    }

    func push() {   // the settings, and the app icon for the sidebar
        send("agents", ["count": agentsUI.count])
        send("dictation", DictationData.state())
        js("st.motion(\(NSWorkspace.shared.accessibilityDisplayShouldReduceMotion))")
        var d: [String: Any] = ["prefs": Prefs.d, "mics": microphoneChoices(), "version": Updater.version, "update": Updater.status, "managedUpdates": Updater.managedByNix,
                                "hotkeyTaken": !hotkeyRegistered, "dictateHotkeyTaken": !Prefs.str("dictateHotkeyLabel").isEmpty && !dictateHotkeyRegistered, "globeTaken": globeKeyTaken()]
        let routines = (Prefs.path as NSString).deletingLastPathComponent + "/routines.json"
        d["routines"] = (try? JSONSerialization.jsonObject(with:Data(contentsOf:URL(fileURLWithPath:routines)))) as? [[String:Any]] ?? []
        // Reminders lists only once Rabik may read them: Settings never asks for access; the first Add to Reminders does
        d["meetingLanguages"] = MeetingSpeech.languages; d["voices"] = Speaker.voices()
        d["reminderLists"] = ((try? CalendarTool.reminders(["action": "reminderLists"], store: calendar))?["lists"] as? [[String: Any]]) ?? []
        if let t = NSApp.applicationIconImage?.tiffRepresentation, let png = NSBitmapImageRep(data: t)?.representation(using: .png, properties: [:]) {
            d["icon"] = "data:image/png;base64," + png.base64EncodedString()
        }
        callJS(web, "st.load", [d])
    }

    func refresh() {   // usage, saved rules, Claude plan: rabik.py --state (it runs Claude Code, so off the main thread)
        DispatchQueue.global().async { [weak self] in
            let p = py(["--state"]), out = Pipe(); p.standardOutput = out
            // Read before waiting: the state (50 recent answers, rules, shortcuts) outgrows the pipe, and a helper blocked
            // on a full pipe never exits, so waiting first hung Settings and left the helper running.
            let data = runToEnd(p, out)
            let s = String(data: data, encoding: .utf8) ?? ""
            guard s.hasPrefix("{") else { return }
            DispatchQueue.main.async { self?.web?.evaluateJavaScript("st.state(\(s))") }
        }
    }
    func feedbackPreview(_ include: Bool, _ text: String, _ revision: Int = 0) {
        feedbackJob += 1; let job = feedbackJob; feedbackURL = nil
        let version = Updater.version.isEmpty ? Bundle.main.object(forInfoDictionaryKey:"CFBundleShortVersionString") as? String ?? "unknown" : Updater.version
        DispatchQueue.global().async { [weak self] in
            let p = py(["--feedback"]), input = Pipe(), out = Pipe(); p.standardInput = input; p.standardOutput = out
            fcntl(input.fileHandleForWriting.fileDescriptor, F_SETNOSIGPIPE, 1)
            do { try p.run(); try input.fileHandleForWriting.write(contentsOf:JSONSerialization.data(withJSONObject:["include":include,"version":version,"text":text])); try input.fileHandleForWriting.close() }
            catch { if p.isRunning { p.terminate() }; DispatchQueue.main.async { if self?.feedbackJob == job { self?.send("feedback", ["error":"Could not prepare feedback. Try again.","revision":revision]) } }; return }
            let data = out.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit()
            var result = (try? JSONSerialization.jsonObject(with:data)) as? [String:Any]; result?["revision"] = revision
            DispatchQueue.main.async { [weak self] in
                guard let self, feedbackJob == job, web != nil else { return }
                guard let result, let text = result["url"] as? String, let url = URL(string:text), text.hasPrefix(repository + "/issues/new?") else { send("feedback", ["error":"Could not prepare feedback. Try again.","revision":revision]); return }
                feedbackURL = url; send("feedback", result)
            }
        }
    }

    // "Change shortcut": the next key chord, including modifier-only and Fn chords, becomes the talk shortcut. Esc cancels.
    var monitor: Any?, recording = "main", recordedModifiers: NSEvent.ModifierFlags = [], echo: ((String) -> Void)?   // echo: setup's page when it records, so it gets the calls Settings would
    func record(_ kind: String = "main", echo: ((String) -> Void)? = nil) {
        if monitor != nil { return }
        recording = kind; recordedModifiers = []; self.echo = echo
        if let r = ref { UnregisterEventHotKey(r); ref = nil }
        if let r = dictateRef { UnregisterEventHotKey(r); dictateRef = nil }   // recorded keys must reach Settings, not either shortcut
        stopSpecialHotkeys()
        let fkeys = [122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111, 105, 107, 113, 106, 64, 79, 80, 90]
        monitor = NSEvent.addLocalMonitorForEvents(matching: [.keyDown, .flagsChanged]) { [weak self] e in
            guard let self else { return e }
            let f = e.modifierFlags.intersection([.command, .shift, .option, .control, .function])
            let mods = shortcutModifierLabel(f)
            if e.type == .flagsChanged {
                if !f.isEmpty { recordedModifiers.formUnion(f); say("rec(\(Hands.quote(shortcutModifierLabel(recordedModifiers))))"); return nil }
                guard !recordedModifiers.isEmpty else { return nil }
                let held = recordedModifiers; recordedModifiers = []
                done((-2, shortcutModifiers(held), shortcutModifierLabel(held)))
                return nil
            }
            if e.keyCode == 53 && f.isEmpty { done(nil); return nil }   // Esc
            let fn = fkeys.firstIndex(of: Int(e.keyCode))
            guard !f.isEmpty || fn != nil else { say("rec(\(Hands.quote("Add ⌃, ⌥, ⇧, ⌘ or fn")))"); return nil }
            let names: [UInt16: String] = [49: "Space", 36: "Return", 48: "Tab", 51: "Delete", 123: "←", 124: "→", 125: "↓", 126: "↑"]
            let key = fn.map { "F\($0 + 1)" } ?? names[e.keyCode] ?? (e.charactersIgnoringModifiers ?? "?").uppercased()
            recordedModifiers = []
            done((Int(e.keyCode), shortcutModifiers(f), mods + key))
            return nil
        }
    }

    func done(_ new: (code: Int, mods: Int, label: String)?) {
        if let m = monitor { NSEvent.removeMonitor(m); monitor = nil }
        let stem = recording == "dictate" ? "dictateHotkey" : "hotkey"
        let old = (Prefs.d[stem + "Code"], Prefs.d[stem + "Mods"], Prefs.d[stem + "Label"])
        if let n = new { Prefs.set(stem + "Code", n.code); Prefs.set(stem + "Mods", n.mods); Prefs.set(stem + "Label", n.label) }
        let otherRegistered = recording == "dictate" ? registerHotkey() : registerDictateHotkey()
        let registered = otherRegistered && (recording == "dictate" ? registerDictateHotkey() : registerHotkey())
        if !registered {   // taken by another app or the other Rabik shortcut: keep the old one
            let own = new != nil && !Prefs.str("dictateHotkeyLabel").isEmpty && hotkeysConflict(hotkey(),dictateHotkey())
            Prefs.set(stem + "Code", old.0!); Prefs.set(stem + "Mods", old.1!); Prefs.set(stem + "Label", old.2!)
            registerHotkey(); registerDictateHotkey()
            say("taken(\(Hands.quote(recording)),\(own))")
        }
        echo?("recorded(\(Hands.quote(Prefs.str(stem + "Label"))))"); echo = nil
        recording = "main"
        push()
    }

    func say(_ call: String) { if let echo { echo(call) } else { js("st." + call) } }
    func js(_ s: String) { web?.evaluateJavaScript(s) }

    func helper(_ args: [String]) { let p = py(args); try? p.run(); p.waitUntilExit() }

    func importProfile() {
        DispatchQueue.global().async { [weak self] in
            let p = py(["--me", "import"]), out = Pipe(); p.standardOutput = out
            let data = runToEnd(p, out)
            let result = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? ["errors": ["contacts", "mail"]]
            self?.send("profileImport", result)
            DispatchQueue.main.async { self?.refresh() }
        }
    }

    func meetings(_ data: [String: Any], _ done: (([String: Any]) -> Void)? = nil) {
        if data["action"] as? String == "delete" {
            let alert = NSAlert(); alert.messageText = "Delete this meeting?"; alert.informativeText = "Its transcript, notes and recap will be removed from this Mac."; alert.addButton(withTitle: "Delete"); alert.addButton(withTitle: "Cancel")
            guard alert.runModal() == .alertFirstButtonReturn else { done?([:]); return }
        }
        DispatchQueue.global().async { [weak self] in
            let p = py(["--meetings"]), input = Pipe(), output = Pipe(); p.standardInput = input; p.standardOutput = output
            fcntl(input.fileHandleForWriting.fileDescriptor, F_SETNOSIGPIPE, 1)
            var result: [String: Any] = ["error": "Could not open saved meetings. Try again."]
            do {
                try p.run(); try input.fileHandleForWriting.write(contentsOf: JSONSerialization.data(withJSONObject: data)); try input.fileHandleForWriting.close()
                let body = output.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit()
                result = (try? JSONSerialization.jsonObject(with: body)) as? [String: Any] ?? result
            } catch { }
            let reply = result
            DispatchQueue.main.async {
                if reply["deleted"] as? String == meeting.archive?.id { meeting.archive = nil; meeting.js("saving", false) }
                if let done { done(reply) } else { self?.send("meetings", reply) }
            }
        }
    }

    func exportMeeting(_ id: String) {
        meetings(["action": "export", "id": id]) { [weak self] result in
            guard let markdown = result["markdown"] as? String else { self?.send("meetings", result); return }
            let chooser = NSSavePanel(); chooser.allowedContentTypes = [UTType(filenameExtension: "md") ?? .plainText];   // .markdown is macOS 27+ chooser.nameFieldStringValue = "Meeting.md"
            chooser.begin { response in
                guard response == .OK, let url = chooser.url else { return }
                do { try MeetingArchive.export(markdown, to: url); self?.send("meetings", ["notice": "Markdown exported."]) }
                catch { self?.send("meetings", ["error": "Could not export. Try another location."]) }
            }
        }
    }

    func apply(_ k: String, _ v: Any) {   // one setting changed, from this window or by voice (rabik.py --set)
        if k == "meetingSave", v as? Bool == false, Prefs.bool("meetingSave") {
            guard Prefs.set(k, false) else { push(); send("notice", ["text": "Couldn’t save that change, so the old setting is back."]); return }
            meeting.savingChanged(false); push()
            let alert = NSAlert(); alert.messageText = "Keep your saved meetings?"; alert.informativeText = "New transcripts will no longer be saved. You can keep or delete the meetings already on this Mac."; alert.addButton(withTitle: "Keep Meetings"); alert.addButton(withTitle: "Delete All Meetings")
            if alert.runModal() == .alertSecondButtonReturn { meetings(["action": "clear"]) }
            return
        }
        guard Prefs.set(k, v) else { push(); send("notice", ["text": "Couldn’t save that change, so the old setting is back."]); return }
        if k == "draw", v as? Bool == false { app.drawing.clear(); app.unwarm() }
        if k == "meetingSave" { meeting.savingChanged(v as? Bool == true) }
        if k == "meeting", v as? Bool == false { meeting.stop() }
        if k == "meetingNudge", v as? Bool == true, EKEventStore.authorizationStatus(for: .event) != .fullAccess {
            calendar.requestFullAccessToEvents { ok, _ in if !ok { DispatchQueue.main.async { Prefs.set("meetingNudge", false); settings.push() } } }
        }
        if ["routing", "model", "client", "apiBase", "apiKey", "apiModel"].contains(k) {   // a new key must not reuse a worker started with the old one
            app.unwarm(); app.js("models", app.modelChoices())
            if meeting.answering == nil {
                meeting.answerOutput?.fileHandleForReading.readabilityHandler = nil; meeting.answerProcess?.terminate()
                meeting.answerProcess = nil; meeting.answerInput = nil; meeting.answerOutput = nil
                meeting.warmAnswer()
            }
        }
        if k == "speechModel" { app.prepareSpeech() }
        if k == "boxPosition" { app.placeBox() }
        if k == "recap" || k == "recapAt" { dailyRecap.sync() }
        if k == "activity" { activity.sync() }
        if k == "improve" { Prefs.set("improveAsked", true) }   // any answer, here or in setup or the card, is the answer
        if k == "speak" { if v as? Bool == true { siriVoice() } else { app.shush() } }
        if k == "hideWhenSharing" { NSApp.windows.forEach(applySharing) }
        if k == "menuIcon" { bar.item.isVisible = v as? Bool == true }
        if k == "paused" { if v as? Bool == true { meeting.stop(paused: true); app.close(clear: false); agentsUI.stopAll() }; bar.paint() }
        if k == "safe" { app.js("mode", v as? Bool == true) }
        if k == "login" {   // App/LoginItem.swift: a login item in a release, build.sh's LaunchAgent from source
            if ProcessInfo.processInfo.environment["RABIK_DIR"] != nil { Prefs.set("login",false); push(); return }
            if !LoginItem.set(v as? Bool == true) {
                Prefs.set("login", LoginItem.current() ?? false); push()
                send("notice", ["text": "macOS didn’t allow that. Check System Settings → General → Login Items."])
            }
        }
    }

    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) { if m.frameInfo.isMainFrame, let b = m.body as? [String: Any] { handle(b) } }

    func confirm(_ title: String, _ detail: String, _ button: String) -> Bool {
        let alert = NSAlert(); alert.messageText = title; alert.informativeText = detail; alert.addButton(withTitle: button); alert.addButton(withTitle: "Cancel")
        return alert.runModal() == .alertFirstButtonReturn
    }

    func handle(_ b: [String: Any]) {
        guard let what = b["do"] as? String else { return }
        switch what {
        case "feedbackInvalidate": feedbackJob += 1; feedbackURL = nil
        case "feedbackPreview": feedbackPreview(b["include"] as? Bool ?? false, b["text"] as? String ?? "", b["revision"] as? Int ?? 0)
        case "feedbackOpen": if let feedbackURL { NSWorkspace.shared.open(feedbackURL) }
        case "meetings": meetings(["action": "list", "query": b["query"] as? String ?? ""])
        case "meetingOpen": if let id = b["id"] as? String { meetings(["action": "get", "id": id]) }
        case "meetingDelete": if let id = b["id"] as? String { meetings(["action": "delete", "id": id]) }
        case "meetingExport": if let id = b["id"] as? String { exportMeeting(id) }
        case "meetingShare": shareText(b["text"] as? String ?? "", in: web, at: b["rect"] as? [Double] ?? [])
        case "meetingRemind":
            if let id = b["id"] as? String, let keys = b["keys"] as? [String] { dailyRecap.add("meeting:" + id, keys) { [weak self] in self?.send("meetingReminded", $0) } }
        case "meetingCopy": if let text = b["text"] as? String { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(text, forType: .string); send("meetings", ["notice": "Copied."]) }
        case "meetingPrepPrompt": NSPasteboard.general.clearContents(); NSPasteboard.general.setString(meetingPrepPrompt, forType: .string); send("meetings", ["notice": "Prep prompt copied."])
        case "meetingPrepOpen": if Prefs.bool("meeting") { meeting.open() }
        case "meetingDemo": if Prefs.bool("meeting") { meeting.open(demo: true) }
        case "set":
            guard let k = b["k"] as? String, let v = b["v"] else { return }
            apply(k, v)
        case "mcpStatus", "mcpAdd":   // Settings → Rabik in Claude Code / ChatGPT: each app's own `mcp add`, on the user's click (brain/mcp.py)
            let arg = b["do"] as? String == "mcpAdd" ? "--mcp-install" : "--mcp-status"
            let target = b["target"] as? String == "chatgpt" ? ["chatgpt"] : []
            DispatchQueue.global().async { [weak self] in
                let p = py([arg] + target), out = Pipe(); p.standardOutput = out; p.standardError = FileHandle.nullDevice
                self?.send("mcp", (try? JSONSerialization.jsonObject(with: runToEnd(p, out))) as? [String: Any] ?? ["added": false, "error": "Could not reach Claude Code."])
            }
        case "mcpCopy":   // Claude Desktop: its own settings file stays the user's to edit
            let config: [String: Any] = ["mcpServers": ["rabik": ["command": "/bin/sh", "args": [dir + "/rabik.py", "--mcp"]]]]
            guard let data = try? JSONSerialization.data(withJSONObject: config, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]) else { return }
            NSPasteboard.general.clearContents(); NSPasteboard.general.setString(String(decoding: data, as: UTF8.self), forType: .string)
            send("notice", ["text": "Copied. In Claude Desktop, open Settings → Developer → Edit Config and paste it."])
        case "goals":   // Settings → General → Goals: list, add, done, undo, drop (brain/goals.py)
            guard let args = b["args"] as? [String], let first = args.first, ["list", "add", "done", "undo", "drop"].contains(first), args.count <= 2 else { return }
            DispatchQueue.global().async { [weak self] in
                let p = py(["--goals"] + args), out = Pipe(); p.standardOutput = out; p.standardError = FileHandle.nullDevice
                self?.send("goals", (try? JSONSerialization.jsonObject(with: runToEnd(p, out))) as? [String: Any] ?? ["error": "Could not save goals."])
            }
        case "people":   // Settings → People: everyone met in saved meetings or told about, built fresh by brain/people.py
            DispatchQueue.global().async { [weak self] in
                let p = py(["--people", "list"]), out = Pipe(); p.standardOutput = out; p.standardError = FileHandle.nullDevice
                let value = (try? JSONSerialization.jsonObject(with: runToEnd(p, out))) as? [String: Any] ?? ["error": "Could not read people. Try again."]
                self?.send("people", value)
            }
        case "activityClear":
            guard confirm("Clear activity history?", "Every page, file and window Rabik noted on this Mac is deleted.", "Clear") else { return }
            activity.clear(); send("notice", ["text": "Activity history cleared."])
        case "activityExcludeAdd":   // Don't record: an app picked in /Applications
            let panel = NSOpenPanel(); panel.directoryURL = URL(fileURLWithPath: "/Applications"); panel.allowedContentTypes = [.applicationBundle]; panel.prompt = "Don’t Record"
            guard panel.runModal() == .OK, let url = panel.url, let id = Bundle(url: url)?.bundleIdentifier else { return }
            var list = Prefs.d["activityExclude"] as? [[String: String]] ?? []
            if !list.contains(where: { $0["id"] == id }) { list.append(["id": id, "name": FileManager.default.displayName(atPath: url.path).replacingOccurrences(of: ".app", with: "")]) }
            apply("activityExclude", list); push()
        case "dictationWord":
            if let word = b["word"] as? String, DictationData.word(word, replacing: b["old"] as? String) { send("dictation", DictationData.state()) }
            else { send("notice", ["text": "Couldn’t save that word. Use 1–80 characters, up to 500 words and 4,000 characters total."]) }
        case "dictationWordDelete":
            if let word = b["word"] as? String, DictationData.forget(word) { send("dictation", DictationData.state()) }
            else { send("notice", ["text": "Couldn’t remove that word."]) }
        case "dictationDelete", "dictationClear":
            let old = DictationData.archive
            if what == "dictationClear" { DictationData.archive.history = [] }
            else { DictationData.archive.history.removeAll { $0.id == b["id"] as? String } }
            if !DictationData.save() { DictationData.archive = old; send("notice", ["text": "Couldn’t delete saved dictation."]) }
            send("dictation", DictationData.state())
        case "record": record()
        case "recordDictate": record("dictate")
        case "cancelRecord": if monitor != nil { done(nil) }
        case "clearDictate":
            if let m = monitor { NSEvent.removeMonitor(m); monitor = nil }
            Prefs.set("dictateHotkeyOff", true); recording = "dictate"; done((-1, 0, ""))
        case "unlearn":
            guard let say = b["say"] as? String else { return }
            DispatchQueue.global().async { [weak self] in self?.helper(["--unlearn", say]); DispatchQueue.main.async { self?.refresh() } }
        case "checkUpdate": Updater.check { [weak self] in self?.push() }
        case "agents": agentsUI.openView()
        case "routineRemove":
            guard let id = b["id"] as? String else { return }
            DispatchQueue.global().async { [weak self] in self?.helper(["--routine","remove",id]); DispatchQueue.main.async { self?.push() } }
        case "github": NSWorkspace.shared.open(URL(string: repository)!)
        case "resetHotkey":
            done((49, controlKey | optionKey, "⌃⌥Space"))   // same rollback and warning as a recorded shortcut
        case "preview":
            if let n = b["sound"] as? String { app.sound(n, Float(Prefs.num("volume"))) }
        case "setup": onboarding.open()
        case "models":   // Bind the response to the saved server that was actually probed.
            let base = Prefs.str("apiBase"), key = Prefs.str("apiKey")
            DispatchQueue.global().async { [weak self] in
                let p = py(["--models"], ["RABIK_PROBE_BASE":base, "RABIK_PROBE_KEY":key]), out = Pipe(); p.standardOutput = out
                let d = runToEnd(p, out)
                self?.send("models", ["base":base, "key":key, "list":(try? JSONSerialization.jsonObject(with: d)) as? [String] ?? []])
            }
        case "localServers": detectLocalServers { [weak self] found in self?.send("local", found) }
        case "copy": if let text = b["text"] as? String { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(text, forType: .string); send("notice", ["text": "Copied."]) }
        case "globeKey": NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.Keyboard-Settings.extension")!)
        case "openLog": NSWorkspace.shared.open(URL(fileURLWithPath:(Prefs.path as NSString).deletingLastPathComponent + "/log.jsonl"))
        case "clearRecent":
            guard confirm("Forget this conversation?", "Follow-ups like “open the second one” will start fresh.", "Forget") else { return }
            try? FileManager.default.removeItem(atPath: app.recent); app.lastDone = .distantPast; send("notice", ["text": "Conversation forgotten."])
        case "profileImport": importProfile()   // the button is the only path that requests Contacts/Mail access
        case "me":
            guard let action = b["action"] as? String else { return }
            var args = ["--me", action]
            switch action {
            case "add":
                guard let category = b["category"] as? String, let text = b["text"] as? String else { return }; args += [category, text]
            case "set":
                guard let id = b["id"] as? String, let text = b["text"] as? String else { return }; args += [id, text]
            case "drop":
                guard let id = b["id"] as? String else { return }; args.append(id)
            case "forget-source":
                guard let source = b["source"] as? String, confirm("Forget everything from \(source)?", "These details are removed from About you. This can’t be undone.", "Forget") else { return }; args.append(source)
            default: return
            }
            DispatchQueue.global().async { [weak self] in self?.helper(args); DispatchQueue.main.async { self?.refresh() } }
        case "forget", "remember":
            guard let line = b["line"] as? String else { return }
            DispatchQueue.global().async { [weak self] in self?.helper(["--" + what, line]); DispatchQueue.main.async { self?.refresh() } }
        case "rule":   // a rule edited in place
            guard let old = b["old"] as? String, let text = b["text"] as? String else { return }
            DispatchQueue.global().async { [weak self] in self?.helper(["--rule", old, text]); DispatchQueue.main.async { self?.refresh() } }
        case "apps": Apps.q.async { [weak self] in self?.send("apps", Apps.list()) }
        case "allow":
            guard let ids = b["ids"] as? [String] else { return }
            Apps.job += 1; let me = Apps.job
            Apps.q.async { [weak self] in
                Apps.current = me
                Apps.allow(ids) { id, s in self?.send("appStatus", [id, s]) }
                self?.send("allowDone", [Any]())
            }
        case "grant": if let id = b["id"] as? String { onboarding.grant(id) }
        case "enableAll": onboarding.enableAll(connected: b["connected"] as? String == "true")
        case "connectors": onboarding.grant("connectors")
        case "stopAllow": Apps.job += 1
        case "automation": NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation")!)
        case "quit": NSApp.terminate(nil)
        default: break
        }
    }

    func windowDidResignKey(_ n: Notification) { if monitor != nil { done(nil) } }

    func windowWillClose(_ n: Notification) {
        feedbackJob += 1; feedbackURL = nil
        if let v = web { v.evaluateJavaScript("st.flush()") { [weak self] r, _ in _ = v; if let b = r as? [String: Any] { self?.handle(b) } } }   // a deletion still showing Undo
        if monitor != nil { done(nil) }   // closed mid-recording: keep the old shortcut
        timer?.invalidate(); timer = nil
        web?.configuration.userContentController.removeScriptMessageHandler(forName: "st")
        win?.setFrameAutosaveName("")   // frees the name for the next window; the frame is already saved
        web = nil; win = nil
    }
}

// The page fills the window under its title bar and would swallow drags; this strip moves the window and double-click zooms.
final class TitleBar: NSView {
    override func mouseDown(with e: NSEvent) {
        guard e.clickCount == 2 else { window?.performDrag(with: e); return }
        switch UserDefaults.standard.string(forKey: "AppleActionOnDoubleClick") { case "Minimize": window?.miniaturize(nil); case "None": break; default: window?.zoom(nil) }
    }
}
