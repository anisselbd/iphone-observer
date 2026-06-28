import SwiftUI

struct StatePill: View {
    let state: String
    private var color: Color {
        switch state {
        case "connected": return .green
        case "connecting", "reconnecting", "reconnexion", "lancement du collector": return .yellow
        case "stopped", "deconnecte": return .red
        default: return .gray
        }
    }
    private var label: String {
        switch state {
        case "connected": return "connecte"
        case "connecting": return "connexion"
        case "reconnecting", "reconnexion": return "reconnexion"
        case "stopped": return "arrete"
        case "deconnecte": return "deconnecte"
        default: return state
        }
    }
    var body: some View {
        Text(label)
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 10).padding(.vertical, 4)
            .background(color.opacity(0.18))
            .foregroundStyle(color)
            .clipShape(Capsule())
    }
}

struct Metric: View {
    let label: String
    let value: String
    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label).font(.caption2).foregroundStyle(.secondary).textCase(.uppercase)
            Text(value).font(.system(.title3, design: .rounded)).monospacedDigit()
        }
        .padding(10)
        .frame(minWidth: 110, alignment: .leading)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 8))
    }
}

struct DashboardView: View {
    @EnvironmentObject var client: CollectorClient

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            indexingBanner
            batteryRow
            TabView {
                ProcessTab().tabItem { Text("Process") }
                NetworkTab().tabItem { Text("Reseau") }
                LogsTab().tabItem { Text("Logs") }
            }
        }
        .padding(16)
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("iphone-observer").font(.headline)
                Text(client.device).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            if client.sidecarManaged {
                Label("collector lance par l'app", systemImage: "bolt.horizontal.circle")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            StatePill(state: client.state)
        }
    }

    @ViewBuilder private var indexingBanner: some View {
        if let idx = client.indexing {
            HStack(spacing: 8) {
                Circle()
                    .fill(idx.state == "indexing" ? Color.yellow : (idx.state == "idle" ? .green : .gray))
                    .frame(width: 10, height: 10)
                Text(idx.label).font(.callout.weight(.semibold))
                if idx.state == "indexing" && idx.activeNow {
                    Text("\(Int(idx.activeCpu)) % CPU cumule").font(.caption).foregroundStyle(.secondary)
                } else if idx.state == "idle" {
                    Text("calme depuis \(idx.quietForS) s").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
            }
            .padding(10)
            .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 8))
        }
    }

    @ViewBuilder private var batteryRow: some View {
        if let b = client.battery {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 10) {
                    Metric(label: "Niveau", value: b.levelPct.map { "\($0) %" } ?? "n/d")
                    Metric(label: "Etat", value: b.stateLabel)
                    Metric(label: "Temperature", value: b.temperatureC.map { String(format: "%.1f C", $0) } ?? "n/d")
                    Metric(label: "Voltage", value: b.voltageV.map { String(format: "%.3f V", $0) } ?? "n/d")
                    Metric(label: "Amperage", value: b.amperageMa.map { "\($0) mA" } ?? "n/d")
                    Metric(label: "Cycles", value: b.cycleCount.map { "\($0)" } ?? "n/d")
                    Metric(label: "Sante", value: healthText(b))
                    Metric(label: "Chargeur", value: b.adapter ?? "aucun")
                }
            }
        }
    }

    private func healthText(_ b: Battery) -> String {
        guard let h = b.healthPct else { return "n/d" }
        if let f = b.fullCapacity, let d = b.designCapacity {
            return String(format: "%.1f %% (%d/%d)", h, f, d)
        }
        return String(format: "%.1f %%", h)
    }
}

struct ProcessTab: View {
    @EnvironmentObject var client: CollectorClient

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let t = client.totals {
                Text("\(t.processCount) process, CPU agrege \(Int(t.aggregateCpu)) %, RAM \(String(format: "%.0f", t.rssMbTotal)) Mo, top \(t.topName) (\(String(format: "%.0f", t.topCpu)) %)")
                    .font(.caption).foregroundStyle(.secondary)
            }
            // Triee par CPU desc cote client. Pas de tri interactif live: evite la
            // re-entrance du NSTableView avec un flux qui change chaque seconde.
            Table(client.processes) {
                TableColumn("PID") { Text("\($0.pid)").monospacedDigit() }
                    .width(min: 60, ideal: 70)
                TableColumn("Process") { Text($0.name) }
                TableColumn("CPU %") { Text(String(format: "%.1f", $0.cpu)).monospacedDigit() }
                    .width(min: 70, ideal: 80)
                TableColumn("RAM (Mo)") { Text(String(format: "%.1f", $0.rssMb)).monospacedDigit() }
                    .width(min: 80, ideal: 90)
                TableColumn("Threads") { Text("\($0.threads)").monospacedDigit() }
                    .width(min: 70, ideal: 80)
            }
        }
    }
}

struct NetworkTab: View {
    @EnvironmentObject var client: CollectorClient

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(client.netSummary).font(.caption).foregroundStyle(.secondary)
            Table(client.connections) {
                TableColumn("PID") { c in Text(c.pid >= 0 ? "\(c.pid)" : "systeme").monospacedDigit() }
                    .width(min: 60, ideal: 70)
                TableColumn("Distant") { c in Text(c.remote).font(.system(.body, design: .monospaced)) }
                TableColumn("Iface") { c in Text(c.iface) }.width(min: 70, ideal: 80)
                TableColumn("Down") { c in Text(formatRate(c.rxRate)).monospacedDigit() }.width(min: 80)
                TableColumn("Up") { c in Text(formatRate(c.txRate)).monospacedDigit() }.width(min: 80)
                TableColumn("RTT") { c in Text(c.rttMs.map { String(format: "%.0f ms", $0) } ?? "-").monospacedDigit() }
                    .width(min: 70)
                TableColumn("Total") { c in Text(formatBytes(c.total)).monospacedDigit() }.width(min: 80)
            }
        }
    }
}

struct LogsTab: View {
    @EnvironmentObject var client: CollectorClient

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 2) {
                    ForEach(client.logs) { line in
                        HStack(alignment: .top, spacing: 6) {
                            Text(line.time).foregroundStyle(.tertiary)
                            Text(line.process).foregroundStyle(.tint)
                            Text(line.message)
                                .foregroundStyle(line.level == "Error" || line.level == "Fault" ? .red : .secondary)
                        }
                        .font(.system(.caption, design: .monospaced))
                        .id(line.id)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(8)
            }
            .onChange(of: client.logs.count) { _, _ in
                if let last = client.logs.last { proxy.scrollTo(last.id, anchor: .bottom) }
            }
        }
    }
}
