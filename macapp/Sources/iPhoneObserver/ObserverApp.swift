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
            // Indicateur live dans la barre de menus: CPU normalise sur les coeurs.
            let util = client.totals.map { Int(min(100, $0.aggregateCpu / Double(max(1, client.cpuCores)))) }
            Label(util.map { "\($0)%" } ?? "iPhone", systemImage: "iphone.gen3")
        }
        .menuBarExtraStyle(.window)
    }
}

struct MenuBarView: View {
    @EnvironmentObject var client: CollectorClient

    private var cpuUtil: Double {
        guard let t = client.totals else { return 0 }
        return min(100, t.aggregateCpu / Double(max(1, client.cpuCores)))
    }
    private var cpuSpark: [TimelinePoint] {
        let cores = Double(max(1, client.cpuCores))
        return (client.timeline?.cpu ?? []).map { TimelinePoint(t: $0.t, v: $0.v / cores) }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                VStack(alignment: .leading, spacing: 1) {
                    Text("iphone-observer").font(.headline)
                    Text(client.device).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer()
                StatePill(state: client.state)
            }

            if client.hasData {
                miniMetric("CPU", "\(Int(cpuUtil)) %", cpuSpark, .accentBlue)
                if !(client.timeline?.net ?? []).isEmpty {
                    miniMetric("Reseau", client.netSummary.isEmpty ? "-" : netShort,
                               client.timeline?.net ?? [], .okGreen)
                }
                HStack(spacing: 14) {
                    if let m = client.memory {
                        compact("RAM", String(format: "%.1f/%.0f Go", m.usedGo, m.totalGo))
                    }
                    if let g = client.graphics, g.available {
                        compact("GPU", g.gpuUtil.map { "\(Int($0)) %" } ?? "-")
                        compact("FPS", g.fps.map { "\(Int($0))" } ?? "-")
                    }
                }
                if let b = client.battery {
                    Label("\(b.levelPct.map { "\($0) %" } ?? "?") · \(b.temperatureC.map { String(format: "%.1f C", $0) } ?? "?") · \(b.stateLabel)",
                          systemImage: "battery.100").font(.caption)
                }
                if let idx = client.indexing {
                    Label(idx.label, systemImage: "magnifyingglass").font(.caption)
                        .foregroundStyle(idx.state == "indexing" ? Color.warnYellow : .secondary)
                }
                if let top = topProcesses, !top.isEmpty {
                    Divider()
                    Text("Top process").font(.caption2).foregroundStyle(.tertiary)
                    ForEach(top) { p in
                        HStack {
                            Text(p.name).font(.caption).lineLimit(1)
                            Spacer()
                            Text(String(format: "%.0f %%", p.cpu)).font(.caption).monospacedDigit()
                                .foregroundStyle(p.cpu >= 30 ? Color.warnYellow : .secondary)
                        }
                    }
                }
            } else {
                Text("En attente de l'iPhone...").font(.caption).foregroundStyle(.secondary)
            }

            Divider()
            Button("Quitter") { NSApp.terminate(nil) }
        }
        .padding(12)
        .frame(width: 280)
    }

    private var netShort: String {
        // Resume reseau compact (derniere valeur de la timeline).
        guard let last = client.timeline?.net.last else { return "-" }
        return formatRate(Int(last.v))
    }
    private var topProcesses: [ProcessRow]? {
        Array(client.processes.sorted { $0.cpu > $1.cpu }.prefix(3))
    }

    private func miniMetric(_ title: String, _ value: String, _ pts: [TimelinePoint], _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack {
                Text(title).font(.caption).foregroundStyle(.secondary)
                Spacer()
                Text(value).font(.caption.weight(.semibold)).foregroundStyle(color).monospacedDigit()
            }
            Sparkline(points: pts, color: color).frame(height: 24)
        }
    }

    private func compact(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(title).font(.caption2).foregroundStyle(.tertiary)
            Text(value).font(.caption.weight(.medium)).monospacedDigit()
        }
    }
}
