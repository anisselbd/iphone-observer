import SwiftUI

struct WaitingView: View {
    @EnvironmentObject var client: CollectorClient

    private var message: String {
        if let e = client.lastError, !e.isEmpty { return e }
        switch client.state {
        case "lancement du collector": return "Demarrage du collector..."
        case "connecting", "connexion", "connected": return "Connexion a l'iPhone..."
        default: return "Branche ton iPhone en USB et deverrouille-le."
        }
    }

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "iphone.gen3")
                .font(.system(size: 54))
                .foregroundStyle(.secondary)
            Text("En attente de l'iPhone")
                .font(.title2.weight(.semibold))
            Text(message)
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 480)
            ProgressView().controlSize(.small).padding(.vertical, 4)
            VStack(alignment: .leading, spacing: 6) {
                checkItem("Branche l'iPhone en USB")
                checkItem("Deverrouille-le")
                checkItem("Mode developpeur active (Reglages > Confidentialite et securite)")
            }
            .font(.callout)
            .foregroundStyle(.secondary)
            if client.sidecarManaged {
                Label("collector lance par l'app", systemImage: "bolt.horizontal.circle")
                    .font(.caption2).foregroundStyle(.tertiary).padding(.top, 4)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(40)
    }

    private func checkItem(_ text: String) -> some View {
        HStack(spacing: 8) {
            Image(systemName: "circle.dotted")
            Text(text)
        }
    }
}

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
        Group {
            if client.hasData {
                dashboard
            } else {
                WaitingView()
            }
        }
    }

    private var dashboard: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            indexingBanner
            batteryRow
            TabView {
                ProcessTab().tabItem { Text("Process") }
                TimelineNativeView().tabItem { Text("Timeline") }
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
    @State private var sortOrder = [KeyPathComparator(\ProcessRow.cpu, order: .reverse)]
    @State private var query = ""

    private var rows: [ProcessRow] {
        let base = query.isEmpty
            ? client.processes
            : client.processes.filter { $0.name.localizedCaseInsensitiveContains(query) }
        return base.sorted(using: sortOrder)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                if let t = client.totals {
                    Text("\(t.processCount) process, CPU agrege \(Int(t.aggregateCpu)) %, RAM \(String(format: "%.0f", t.rssMbTotal)) Mo, top \(t.topName) (\(String(format: "%.0f", t.topCpu)) %)")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                TextField("Filtrer", text: $query)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 200)
            }
            // Tri interactif par colonne (defaut: CPU desc).
            Table(rows, sortOrder: $sortOrder) {
                TableColumn("PID", value: \.pid) { Text("\($0.pid)").monospacedDigit() }
                    .width(min: 60, ideal: 70)
                TableColumn("Process", value: \.name) { Text($0.name) }
                TableColumn("CPU %", value: \.cpu) { Text(String(format: "%.1f", $0.cpu)).monospacedDigit() }
                    .width(min: 70, ideal: 80)
                TableColumn("RAM (Mo)", value: \.rssMb) { Text(String(format: "%.1f", $0.rssMb)).monospacedDigit() }
                    .width(min: 80, ideal: 90)
                TableColumn("Threads", value: \.threads) { Text("\($0.threads)").monospacedDigit() }
                    .width(min: 70, ideal: 80)
            }
        }
    }
}

struct TimelineNativeView: View {
    @EnvironmentObject var client: CollectorClient

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let tl = client.timeline,
               !(tl.cpu.isEmpty && tl.temp.isEmpty && tl.net.isEmpty) {
                legend(tl)
                Canvas { ctx, size in draw(ctx, size, tl) }
                    .background(Color.black.opacity(0.25), in: RoundedRectangle(cornerRadius: 8))
                Text("\(Int(tl.minutes)) dernieres minutes, \(tl.totalRows) events stockes")
                    .font(.caption2).foregroundStyle(.tertiary)
            } else {
                Spacer()
                Text("Timeline en cours de remplissage...")
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity)
                Spacer()
            }
        }
    }

    private func legend(_ tl: TimelineData) -> some View {
        HStack(spacing: 16) {
            legendItem(.blue, "CPU agrege", tl.cpu.last.map { "\(Int($0.v)) %" })
            legendItem(.orange, "Temp batterie", tl.temp.last.map { String(format: "%.1f C", $0.v) })
            legendItem(.green, "Reseau", tl.net.last.map { formatRate(Int($0.v)) })
            Spacer()
        }
        .font(.caption)
    }

    private func legendItem(_ color: Color, _ name: String, _ value: String?) -> some View {
        HStack(spacing: 6) {
            RoundedRectangle(cornerRadius: 2).fill(color).frame(width: 14, height: 3)
            Text(name).foregroundStyle(.secondary)
            Text(value ?? "n/d").monospacedDigit()
        }
    }

    private func draw(_ ctx: GraphicsContext, _ size: CGSize, _ tl: TimelineData) {
        let W = size.width, H = size.height
        let padB: CGFloat = 14, padT: CGFloat = 8
        let plotH = H - padB - padT
        let span = max(1, tl.until - tl.since)
        func x(_ t: Double) -> CGFloat { CGFloat((t - tl.since) / span) * W }

        // Bandes d'indexation en fond.
        for i in tl.indexing.indices where tl.indexing[i].state == "indexing" {
            let x0 = x(tl.indexing[i].t)
            let x1 = i + 1 < tl.indexing.count ? x(tl.indexing[i + 1].t) : W
            let rect = CGRect(x: x0, y: padT, width: max(1, x1 - x0), height: plotH)
            ctx.fill(Path(rect), with: .color(.yellow.opacity(0.10)))
        }

        func line(_ pts: [TimelinePoint], _ color: Color) {
            guard pts.count >= 2 else { return }
            let vs = pts.map(\.v)
            let mn = vs.min()!, mx = Swift.max(vs.max()!, mn + 0.0001)
            var path = Path()
            for (i, p) in pts.enumerated() {
                let px = x(p.t)
                let py = padT + plotH - CGFloat((p.v - mn) / (mx - mn)) * plotH
                if i == 0 { path.move(to: CGPoint(x: px, y: py)) }
                else { path.addLine(to: CGPoint(x: px, y: py)) }
            }
            ctx.stroke(path, with: .color(color), lineWidth: 1.6)
        }
        line(tl.net, .green)
        line(tl.temp, .orange)
        line(tl.cpu, .blue)

        for t in tl.errors {
            let xx = x(t)
            ctx.fill(Path(CGRect(x: xx, y: H - padB + 2, width: 1.5, height: 6)), with: .color(.red))
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
