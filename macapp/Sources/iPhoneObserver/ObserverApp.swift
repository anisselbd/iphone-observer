import SwiftUI
import AppKit

// Force l'app a se comporter en app reguliere meme lancee hors bundle (swift run).
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }
}

@main
struct ObserverApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @StateObject private var client = CollectorClient()

    var body: some Scene {
        WindowGroup("iphone-observer") {
            DashboardView()
                .environmentObject(client)
                .frame(minWidth: 860, minHeight: 600)
                .onAppear {
                    client.start()
                    NotificationManager.shared.requestAuthorization()
                }
        }

        MenuBarExtra {
            MenuBarView().environmentObject(client)
        } label: {
            Image(systemName: "iphone.gen3")
        }
        .menuBarExtraStyle(.window)
    }
}

struct MenuBarView: View {
    @EnvironmentObject var client: CollectorClient

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(client.device).font(.headline)
            HStack { StatePill(state: client.state) }
            if let t = client.totals {
                Label("CPU \(Int(t.aggregateCpu)) %, top \(t.topName)", systemImage: "cpu")
                    .font(.callout)
            }
            if let b = client.battery {
                Label("\(b.levelPct.map { "\($0) %" } ?? "?"), \(b.temperatureC.map { String(format: "%.1f C", $0) } ?? "?")",
                      systemImage: "battery.100")
                    .font(.callout)
            }
            if let idx = client.indexing {
                Label(idx.label, systemImage: "magnifyingglass").font(.callout)
            }
            Divider()
            Button("Quitter") { NSApp.terminate(nil) }
        }
        .padding(12)
        .frame(width: 260)
    }
}
