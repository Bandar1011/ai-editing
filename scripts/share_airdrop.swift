import AppKit

// The user selects the receiving device in Apple's own AirDrop interface.
@MainActor
final class AirDropDelegate: NSObject, NSSharingServiceDelegate {
    let statusURL: URL
    init(_ statusURL: URL) { self.statusURL = statusURL }

    func report(_ status: String, _ message: String, finish: Bool = false) {
        if let data = try? JSONSerialization.data(withJSONObject: ["status": status, "message": message]) {
            try? data.write(to: statusURL, options: .atomic)
        }
        if finish { NSApplication.shared.terminate(nil) }
    }

    func sharingService(_ sharingService: NSSharingService, didShareItems items: [Any]) {
        report("shared", "Shared through AirDrop", finish: true)
    }

    func sharingService(_ sharingService: NSSharingService, didFailToShareItems items: [Any], error: Error) {
        let cancelled = [NSUserCancelledError, -128].contains((error as NSError).code)
        report(cancelled ? "cancelled" : "error",
               cancelled ? "AirDrop cancelled" : error.localizedDescription, finish: true)
    }
}

@main
struct ShareAirDrop {
    @MainActor
    static func main() {
        guard CommandLine.arguments.count == 3 else { exit(2) }
        let file = URL(fileURLWithPath: CommandLine.arguments[1])
        let delegate = AirDropDelegate(URL(fileURLWithPath: CommandLine.arguments[2]))
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        guard FileManager.default.fileExists(atPath: file.path),
              let service = NSSharingService(named: .sendViaAirDrop),
              service.canPerform(withItems: [file]) else {
            delegate.report("error", "AirDrop is unavailable on this Mac.")
            exit(1)
        }
        service.delegate = delegate
        DispatchQueue.main.async {
            app.activate(ignoringOtherApps: true)
            service.perform(withItems: [file])
            delegate.report("choosing", "Choose your iPhone in AirDrop")
        }
        _ = Timer.scheduledTimer(withTimeInterval: 600, repeats: false) { _ in
            MainActor.assumeIsolated { delegate.report("cancelled", "AirDrop timed out. Try again.", finish: true) }
        }
        app.run()
        withExtendedLifetime(delegate) {}
    }
}
