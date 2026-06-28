import SwiftUI
import Charts

// MARK: - Theme

extension Color {
    static let accentBlue = Color(red: 0.31, green: 0.63, blue: 1.0)
    static let okGreen = Color(red: 0.21, green: 0.83, blue: 0.60)
    static let warnYellow = Color(red: 0.98, green: 0.74, blue: 0.14)
    static let errRed = Color(red: 0.97, green: 0.45, blue: 0.45)
}

private let windowBackground = LinearGradient(
    colors: [Color(red: 0.07, green: 0.08, blue: 0.11), Color(red: 0.04, green: 0.05, blue: 0.07)],
    startPoint: .top, endPoint: .bottom
)

struct Card<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        content
            .background(.white.opacity(0.035), in: RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(.white.opacity(0.07)))
    }
}

// MARK: - Dashboard

struct DashboardView: View {
    @EnvironmentObject var client: CollectorClient

    var body: some View {
        ZStack {
            windowBackground.ignoresSafeArea()
            if client.hasData { dashboard } else { WaitingView() }
        }
    }

    private var dashboard: some View {
        VStack(alignment: .leading, spacing: 14) {
            HeaderBar()
            IndexingBanner()
            HeroRow()
            SystemStrip()
            TabView {
                ProcessTab().tabItem { Label("Process", systemImage: "cpu") }
                TimelineTab().tabItem { Label("Timeline", systemImage: "chart.xyaxis.line") }
                NetworkTab().tabItem { Label("Reseau", systemImage: "network") }
                LogsTab().tabItem { Label("Logs", systemImage: "text.alignleft") }
            }
        }
        .padding(18)
    }
}

// MARK: - Header

struct HeaderBar: View {
    @EnvironmentObject var client: CollectorClient

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "iphone.gen3")
                .font(.system(size: 22))
                .foregroundStyle(Color.accentBlue)
            VStack(alignment: .leading, spacing: 1) {
                Text("iphone-observer").font(.headline)
                Text(client.device).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            if client.sidecarManaged {
                Label("collector auto", systemImage: "bolt.horizontal.circle")
                    .font(.caption2).foregroundStyle(.tertiary)
            }
            StatePill(state: client.state)
        }
    }
}

struct StatePill: View {
    let state: String
    private var color: Color {
        switch state {
        case "connected": return .okGreen
        case "connecting", "reconnecting", "reconnexion", "lancement du collector": return .warnYellow
        case "stopped", "deconnecte": return .errRed
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
        HStack(spacing: 7) {
            Circle().fill(color).frame(width: 8, height: 8)
                .shadow(color: color.opacity(0.8), radius: 4)
            Text(label).font(.caption.weight(.semibold))
        }
        .padding(.horizontal, 11).padding(.vertical, 6)
        .background(color.opacity(0.14), in: Capsule())
        .foregroundStyle(color)
    }
}

// MARK: - Indexing banner

struct IndexingBanner: View {
    @EnvironmentObject var client: CollectorClient
    @State private var pulse = false

    var body: some View {
        if let idx = client.indexing {
            let active = idx.state == "indexing"
            let color: Color = active ? .warnYellow : (idx.state == "idle" ? .okGreen : .gray)
            HStack(spacing: 10) {
                Circle().fill(color).frame(width: 10, height: 10)
                    .scaleEffect(active && pulse ? 1.35 : 1)
                    .animation(active ? .easeInOut(duration: 0.8).repeatForever(autoreverses: true) : .default, value: pulse)
                Text(idx.label).font(.callout.weight(.semibold))
                if active && idx.activeNow {
                    Text("\(Int(idx.activeCpu)) % CPU cumule").font(.caption).foregroundStyle(.secondary)
                } else if idx.state == "idle" {
                    Text("calme depuis \(idx.quietForS) s").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
            }
            .padding(.horizontal, 14).padding(.vertical, 11)
            .background(color.opacity(0.10), in: RoundedRectangle(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(color.opacity(0.25)))
            .onAppear { pulse = true }
        }
    }
}

// MARK: - Hero row (batterie + CPU + RAM)

struct HeroRow: View {
    @EnvironmentObject var client: CollectorClient

    var body: some View {
        HStack(spacing: 12) {
            BatteryCard()
            CpuCard()
            RamCard()
        }
        .fixedSize(horizontal: false, vertical: true)
    }
}

struct BatteryRing: View {
    let level: Int
    let charging: Bool
    private var color: Color { level <= 20 ? .errRed : (charging ? .okGreen : .accentBlue) }
    var body: some View {
        ZStack {
            Circle().stroke(.white.opacity(0.08), lineWidth: 7)
            Circle().trim(from: 0, to: CGFloat(max(0, min(100, level))) / 100)
                .stroke(color, style: StrokeStyle(lineWidth: 7, lineCap: .round))
                .rotationEffect(.degrees(-90))
            VStack(spacing: -2) {
                Text("\(level)").font(.system(size: 20, weight: .semibold, design: .rounded))
                Text("%").font(.system(size: 10)).foregroundStyle(.secondary)
            }
        }
        .frame(width: 62, height: 62)
        .animation(.easeOut(duration: 0.4), value: level)
    }
}

struct BatteryCard: View {
    @EnvironmentObject var client: CollectorClient
    var body: some View {
        Card {
            HStack(spacing: 14) {
                if let b = client.battery {
                    BatteryRing(level: b.levelPct ?? 0, charging: b.isCharging)
                    VStack(alignment: .leading, spacing: 5) {
                        Label("Batterie", systemImage: "battery.100").font(.caption).foregroundStyle(.secondary)
                        Text(b.stateLabel).font(.callout.weight(.medium))
                        HStack(spacing: 10) {
                            tempView(b.temperatureC)
                            if let v = b.voltageV { miniStat("\(String(format: "%.2f", v)) V") }
                            if let c = b.cycleCount { miniStat("\(Int(c)) cyc") }
                        }
                        if let h = b.healthPct { miniStat("sante \(String(format: "%.0f", h)) %") }
                    }
                } else {
                    ProgressView().controlSize(.small)
                }
                Spacer(minLength: 0)
            }
            .padding(14)
        }
    }
    private func tempView(_ t: Double?) -> some View {
        let color: Color = (t ?? 0) >= 40 ? .warnYellow : .secondary
        return Label(t.map { String(format: "%.1f C", $0) } ?? "n/d", systemImage: "thermometer.medium")
            .font(.caption).foregroundStyle(color)
    }
    private func miniStat(_ s: String) -> some View {
        Text(s).font(.caption).foregroundStyle(.secondary).monospacedDigit()
    }
}

struct CpuCard: View {
    @EnvironmentObject var client: CollectorClient
    var body: some View {
        let raw = client.totals?.aggregateCpu ?? 0
        let cores = Double(max(1, client.cpuCores))
        let util = Swift.min(100, raw / cores)
        let sparkPts = (client.timeline?.cpu ?? []).map { TimelinePoint(t: $0.t, v: $0.v / cores) }
        return Card {
            VStack(alignment: .leading, spacing: 6) {
                Label("CPU utilisation", systemImage: "cpu").font(.caption).foregroundStyle(.secondary)
                HStack(alignment: .firstTextBaseline, spacing: 4) {
                    Text("\(Int(util))")
                        .font(.system(size: 30, weight: .semibold, design: .rounded))
                    Text("%").foregroundStyle(.secondary)
                }
                Sparkline(points: sparkPts, color: .accentBlue).frame(height: 28)
                Text("\(Int(raw)) % cumule sur \(client.cpuCores) coeurs")
                    .font(.caption2).foregroundStyle(.tertiary)
                if let t = client.totals {
                    Text("top \(t.topName) (\(Int(t.topCpu)) %)")
                        .font(.caption2).foregroundStyle(.tertiary).lineLimit(1)
                }
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

struct RamCard: View {
    @EnvironmentObject var client: CollectorClient
    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 8) {
                Label("Memoire", systemImage: "memorychip").font(.caption).foregroundStyle(.secondary)
                if let m = client.memory {
                    HStack(alignment: .firstTextBaseline, spacing: 5) {
                        Text(String(format: "%.1f", m.usedGo))
                            .font(.system(size: 28, weight: .semibold, design: .rounded))
                        Text("/ \(String(format: "%.0f", m.totalGo)) Go").foregroundStyle(.secondary)
                    }
                    bar(m.fraction)
                    Text("\(Int(m.fraction * 100)) % utilisee · \(client.totals?.processCount ?? 0) process")
                        .font(.caption2).foregroundStyle(.tertiary)
                } else {
                    Text("...").foregroundStyle(.tertiary)
                }
                Spacer(minLength: 0)
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func bar(_ f: Double) -> some View {
        let color: Color = f >= 0.9 ? .errRed : (f >= 0.7 ? .warnYellow : .okGreen)
        return GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(.white.opacity(0.08))
                Capsule().fill(color)
                    .frame(width: geo.size.width * CGFloat(min(1, max(0, f))))
            }
        }
        .frame(height: 6)
        .animation(.easeOut(duration: 0.4), value: f)
    }
}

// MARK: - Bandeau systeme (disque, reseau global, swap, threads)

struct SystemStrip: View {
    @EnvironmentObject var client: CollectorClient
    private var s: SystemStats? { client.systemStats }

    var body: some View {
        Card {
            HStack(spacing: 14) {
                dual(icon: "internaldrive", title: "Disque",
                     down: s?.diskReadBps, up: s?.diskWriteBps, color: .accentBlue, help: nil)
                sep()
                dual(icon: "network", title: "Reseau global",
                     down: s?.netInBps, up: s?.netOutBps, color: .okGreen,
                     help: "Trafic systeme total de l'iPhone. Inclut le lien USB de l'observateur (tunnel), donc superieur au trafic reseau reel.")
                sep()
                single(icon: "arrow.up.arrow.down.circle", title: "Swap",
                       value: client.memory?.swapMb.map { "\($0) Mo" }, color: .warnYellow)
                sep()
                single(icon: "square.stack.3d.up.fill", title: "Threads",
                       value: s?.threads.map { "\($0)" }, color: .accentBlue)
                Spacer(minLength: 0)
            }
            .padding(.vertical, 11).padding(.horizontal, 16)
        }
    }

    private func sep() -> some View {
        Rectangle().fill(.white.opacity(0.08)).frame(width: 1, height: 30)
    }

    private func dual(icon: String, title: String, down: Int?, up: Int?,
                      color: Color, help: String?) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 5) {
                Image(systemName: icon).font(.caption2).foregroundStyle(color)
                Text(title).font(.caption2).foregroundStyle(.secondary)
                if let help {
                    Image(systemName: "info.circle").font(.system(size: 9))
                        .foregroundStyle(.tertiary).help(help)
                }
            }
            HStack(spacing: 10) {
                Label(down.map { formatRate($0) } ?? "n/d", systemImage: "arrow.down")
                    .font(.caption.weight(.medium)).monospacedDigit().foregroundStyle(.primary)
                Label(up.map { formatRate($0) } ?? "n/d", systemImage: "arrow.up")
                    .font(.caption.weight(.medium)).monospacedDigit().foregroundStyle(.primary)
            }
            .labelStyle(.titleAndIcon)
        }
    }

    private func single(icon: String, title: String, value: String?, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 5) {
                Image(systemName: icon).font(.caption2).foregroundStyle(color)
                Text(title).font(.caption2).foregroundStyle(.secondary)
            }
            Text(value ?? "n/d").font(.callout.weight(.semibold)).monospacedDigit()
        }
    }
}

struct Sparkline: View {
    let points: [TimelinePoint]
    let color: Color
    var body: some View {
        if points.count < 2 {
            Text("...").font(.caption2).foregroundStyle(.tertiary)
                .frame(maxWidth: .infinity, alignment: .leading)
        } else {
            Chart {
                ForEach(points.indices, id: \.self) { i in
                    AreaMark(x: .value("i", i), y: .value("v", points[i].v))
                        .foregroundStyle(LinearGradient(colors: [color.opacity(0.35), color.opacity(0.02)],
                                                        startPoint: .top, endPoint: .bottom))
                        .interpolationMethod(.catmullRom)
                    LineMark(x: .value("i", i), y: .value("v", points[i].v))
                        .foregroundStyle(color)
                        .interpolationMethod(.catmullRom)
                }
            }
            .chartXAxis(.hidden).chartYAxis(.hidden)
        }
    }
}

// MARK: - Process tab

struct PidSel: Identifiable { let id: Int }

struct ProcessTab: View {
    @EnvironmentObject var client: CollectorClient
    @State private var sortOrder = [KeyPathComparator(\ProcessRow.cpu, order: .reverse)]
    @State private var query = ""
    @State private var selectedPid: Int?
    @State private var detail: PidSel?

    private var rows: [ProcessRow] {
        let base = query.isEmpty
            ? client.processes
            : client.processes.filter { $0.name.localizedCaseInsensitiveContains(query) }
        return base.sorted(using: sortOrder)
    }

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 12) {
                    Text(client.paused ? "\(client.totals?.processCount ?? 0) process (fige)" : "\(client.totals?.processCount ?? 0) process")
                        .font(.caption).foregroundStyle(client.paused ? Color.warnYellow : .secondary)
                    Spacer()
                    Button { client.paused.toggle() } label: {
                        Image(systemName: client.paused ? "play.fill" : "pause.fill")
                    }
                    .buttonStyle(.borderless)
                    .help(client.paused ? "Reprendre" : "Figer pour lire")
                    Picker("", selection: Binding(get: { client.tableIntervalS },
                                                  set: { client.tableIntervalS = $0 })) {
                        Text("1s").tag(1.0)
                        Text("2s").tag(2.0)
                        Text("5s").tag(5.0)
                    }
                    .pickerStyle(.segmented).labelsHidden().frame(width: 130)
                    HStack(spacing: 6) {
                        Image(systemName: "magnifyingglass").font(.caption).foregroundStyle(.tertiary)
                        TextField("Filtrer", text: $query).textFieldStyle(.plain).frame(width: 150)
                    }
                    .padding(.horizontal, 8).padding(.vertical, 4)
                    .background(.white.opacity(0.05), in: Capsule())
                }
                Table(rows, selection: $selectedPid, sortOrder: $sortOrder) {
                    TableColumn("PID", value: \.pid) { Text("\($0.pid)").monospacedDigit().foregroundStyle(.secondary) }
                        .width(min: 56, ideal: 64)
                    TableColumn("Process", value: \.name) { Text($0.name).fontWeight(.medium) }
                    TableColumn("CPU %", value: \.cpu) { CpuCell(cpu: $0.cpu) }
                        .width(min: 90, ideal: 100)
                    TableColumn("RAM (Mo)", value: \.rssMb) { Text(String(format: "%.1f", $0.rssMb)).monospacedDigit() }
                        .width(min: 80, ideal: 90)
                    TableColumn("Threads", value: \.threads) { Text("\($0.threads)").monospacedDigit().foregroundStyle(.secondary) }
                        .width(min: 64, ideal: 74)
                }
                .tableStyle(.inset(alternatesRowBackgrounds: true))
                .contextMenu(forSelectionType: ProcessRow.ID.self) { ids in
                    if let pid = ids.first {
                        Button("Voir le detail") { detail = PidSel(id: pid) }
                    }
                } primaryAction: { ids in
                    if let pid = ids.first { detail = PidSel(id: pid) }
                }
                Text("Double-clic sur un process pour son historique CPU/RAM.")
                    .font(.caption2).foregroundStyle(.tertiary)
            }
            .padding(12)
        }
        .sheet(item: $detail, onDismiss: { selectedPid = nil }) { sel in
            ProcessDetailView(pid: sel.id).environmentObject(client)
        }
    }
}

// MARK: - Detail process (historique en memoire, session courante)

struct ProcessDetailView: View {
    @EnvironmentObject var client: CollectorClient
    @Environment(\.dismiss) private var dismiss
    let pid: Int

    private var current: ProcessRow? { client.processes.first { $0.pid == pid } }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(client.name(for: pid)).font(.title3.weight(.semibold))
                    Text("PID \(pid)").font(.caption).foregroundStyle(.secondary).monospacedDigit()
                }
                Spacer()
                Button { dismiss() } label: { Image(systemName: "xmark.circle.fill").font(.title2) }
                    .buttonStyle(.borderless).foregroundStyle(.secondary)
            }

            if let c = current {
                HStack(spacing: 18) {
                    stat("CPU", String(format: "%.1f %%", c.cpu), .accentBlue)
                    stat("RAM", String(format: "%.1f Mo", c.rssMb), .okGreen)
                    stat("Threads", "\(c.threads)", .warnYellow)
                }
            } else {
                Text("Process plus visible dans le flux courant.")
                    .font(.caption).foregroundStyle(.secondary)
            }

            // Rafraichissement autonome: relit l'historique en memoire sans
            // dependre d'une publication globale du client.
            TimelineView(.periodic(from: .now, by: 1.5)) { _ in
                let h = client.history(for: pid)
                VStack(alignment: .leading, spacing: 12) {
                    historyChart("CPU %", h.map { TimelinePoint(t: $0.t, v: $0.cpu) },
                                 .accentBlue) { String(format: "%.0f %%", $0) }
                    historyChart("RAM (Mo)", h.map { TimelinePoint(t: $0.t, v: $0.rss) },
                                 .okGreen) { String(format: "%.0f Mo", $0) }
                    Text(h.count >= 2
                         ? "\(h.count) echantillons (1 Hz) sur cette session"
                         : "Historique en cours d'accumulation...")
                        .font(.caption2).foregroundStyle(.tertiary)
                }
            }
        }
        .padding(20)
        .frame(width: 460, height: 420)
        .background(windowBackground)
    }

    private func stat(_ title: String, _ value: String, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.caption2).foregroundStyle(.secondary)
            Text(value).font(.title3.weight(.semibold)).foregroundStyle(color).monospacedDigit()
        }
    }

    private func historyChart(_ title: String, _ pts: [TimelinePoint], _ color: Color,
                              _ fmt: @escaping (Double) -> String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack {
                Text(title).font(.caption).foregroundStyle(.secondary)
                Spacer()
                Text(pts.last.map { fmt($0.v) } ?? "n/d")
                    .font(.caption.weight(.semibold)).foregroundStyle(color).monospacedDigit()
            }
            if pts.count >= 2 {
                Chart {
                    ForEach(pts.indices, id: \.self) { i in
                        let dt = Date(timeIntervalSince1970: pts[i].t)
                        AreaMark(x: .value("t", dt), y: .value("v", pts[i].v))
                            .foregroundStyle(LinearGradient(colors: [color.opacity(0.30), color.opacity(0.02)],
                                                            startPoint: .top, endPoint: .bottom))
                            .interpolationMethod(.catmullRom)
                        LineMark(x: .value("t", dt), y: .value("v", pts[i].v))
                            .foregroundStyle(color).interpolationMethod(.catmullRom)
                    }
                }
                .chartXAxis { AxisMarks(values: .automatic(desiredCount: 3)) }
                .chartYAxis { AxisMarks(position: .leading, values: .automatic(desiredCount: 3)) }
                .frame(height: 120)
            } else {
                RoundedRectangle(cornerRadius: 8).fill(.white.opacity(0.03))
                    .frame(height: 120)
                    .overlay(ProgressView().controlSize(.small))
            }
        }
    }
}

struct CpuCell: View {
    let cpu: Double
    private var color: Color { cpu >= 80 ? .errRed : (cpu >= 30 ? .warnYellow : .primary) }
    var body: some View {
        HStack(spacing: 6) {
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(.white.opacity(0.06))
                    Capsule().fill(color.opacity(0.55))
                        .frame(width: geo.size.width * CGFloat(min(cpu, 100) / 100))
                }
            }
            .frame(width: 36, height: 5)
            Text(String(format: "%.1f", cpu)).monospacedDigit().foregroundStyle(color)
        }
    }
}

// MARK: - Timeline tab (Swift Charts)

struct TimelineTab: View {
    @EnvironmentObject var client: CollectorClient

    var body: some View {
        Card {
            if let tl = client.timeline,
               !(tl.cpu.isEmpty && tl.temp.isEmpty && tl.net.isEmpty) {
                ScrollView {
                    VStack(alignment: .leading, spacing: 10) {
                        let cores = Double(max(1, client.cpuCores))
                        series("CPU utilisation (\(client.cpuCores) coeurs)",
                               tl.cpu.map { TimelinePoint(t: $0.t, v: $0.v / cores) }, .accentBlue) { "\(Int($0)) %" }
                        series("Temperature batterie", tl.temp, .warnYellow) { String(format: "%.1f C", $0) }
                        series("Debit reseau (connexions)", tl.net, .okGreen) { formatRate(Int($0)) }
                        if !tl.diskRead.isEmpty || !tl.diskWrite.isEmpty {
                            series("Disque lecture", tl.diskRead, .accentBlue) { formatRate(Int($0)) }
                            series("Disque ecriture", tl.diskWrite, Color(red: 0.78, green: 0.55, blue: 1.0)) { formatRate(Int($0)) }
                        }
                        if !tl.swap.isEmpty {
                            series("Swap", tl.swap, .warnYellow) { "\(Int($0)) Mo" }
                        }
                        Text("\(Int(tl.minutes)) dernieres minutes, \(tl.totalRows) events stockes")
                            .font(.caption2).foregroundStyle(.tertiary)
                    }
                    .padding(14)
                }
            } else {
                VStack {
                    Spacer()
                    Label("Timeline en cours de remplissage...", systemImage: "hourglass")
                        .foregroundStyle(.secondary).frame(maxWidth: .infinity)
                    Spacer()
                }
                .padding(14)
            }
        }
    }

    private func series(_ title: String, _ pts: [TimelinePoint], _ color: Color,
                        _ fmt: @escaping (Double) -> String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack {
                Text(title).font(.caption).foregroundStyle(.secondary)
                Spacer()
                Text(pts.last.map { fmt($0.v) } ?? "n/d")
                    .font(.caption.weight(.semibold)).foregroundStyle(color).monospacedDigit()
            }
            Chart {
                ForEach(pts.indices, id: \.self) { i in
                    let d = Date(timeIntervalSince1970: pts[i].t)
                    AreaMark(x: .value("t", d), y: .value("v", pts[i].v))
                        .foregroundStyle(LinearGradient(colors: [color.opacity(0.30), color.opacity(0.02)],
                                                        startPoint: .top, endPoint: .bottom))
                        .interpolationMethod(.catmullRom)
                    LineMark(x: .value("t", d), y: .value("v", pts[i].v))
                        .foregroundStyle(color).interpolationMethod(.catmullRom)
                }
            }
            .chartXAxis { AxisMarks(values: .automatic(desiredCount: 4)) }
            .chartYAxis { AxisMarks(position: .leading, values: .automatic(desiredCount: 3)) }
            .frame(height: 72)
        }
    }
}

// MARK: - Network tab

struct NetworkTab: View {
    @EnvironmentObject var client: CollectorClient
    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 8) {
                Text(client.netSummary).font(.caption).foregroundStyle(.secondary)
                Table(client.connections) {
                    TableColumn("Process") { c in
                        Text(c.pid >= 0 ? "\(c.pid)" : "systeme").monospacedDigit().foregroundStyle(.secondary)
                    }.width(min: 60, ideal: 70)
                    TableColumn("Distant") { c in Text(c.remote).font(.system(.body, design: .monospaced)) }
                    TableColumn("Iface") { c in
                        Text(c.iface).padding(.horizontal, 6).padding(.vertical, 1)
                            .background(.white.opacity(0.06), in: Capsule()).font(.caption)
                    }.width(min: 74, ideal: 84)
                    TableColumn("Down") { c in Label(formatRate(c.rxRate), systemImage: "arrow.down").labelStyle(.titleOnly).monospacedDigit() }.width(min: 80)
                    TableColumn("Up") { c in Text(formatRate(c.txRate)).monospacedDigit() }.width(min: 80)
                    TableColumn("RTT") { c in Text(c.rttMs.map { String(format: "%.0f ms", $0) } ?? "-").monospacedDigit().foregroundStyle(.secondary) }.width(min: 66)
                    TableColumn("Total") { c in Text(formatBytes(c.total)).monospacedDigit() }.width(min: 80)
                }
                .tableStyle(.inset(alternatesRowBackgrounds: true))
            }
            .padding(12)
        }
    }
}

// MARK: - Logs tab

struct LogsTab: View {
    @EnvironmentObject var client: CollectorClient
    var body: some View {
        Card {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 3) {
                        ForEach(client.logs) { line in
                            let isErr = line.level == "Error" || line.level == "Fault"
                            HStack(alignment: .top, spacing: 8) {
                                Text(line.time).foregroundStyle(.tertiary)
                                Text(line.process).foregroundStyle(Color.accentBlue)
                                Text(line.message)
                                    .foregroundStyle(isErr ? Color.errRed : .secondary)
                            }
                            .font(.system(.caption, design: .monospaced))
                            .id(line.id)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10)
                }
                .onChange(of: client.logs.count) { _, _ in
                    if let last = client.logs.last { proxy.scrollTo(last.id, anchor: .bottom) }
                }
            }
        }
    }
}

// MARK: - Waiting

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
        VStack(spacing: 18) {
            ZStack {
                Circle().fill(Color.accentBlue.opacity(0.12)).frame(width: 110, height: 110)
                Image(systemName: "iphone.gen3").font(.system(size: 50)).foregroundStyle(Color.accentBlue)
            }
            Text("En attente de l'iPhone").font(.title2.weight(.semibold))
            Text(message)
                .font(.callout).foregroundStyle(.secondary)
                .multilineTextAlignment(.center).frame(maxWidth: 480)
            ProgressView().controlSize(.small)
            VStack(alignment: .leading, spacing: 8) {
                checkItem("Branche l'iPhone en USB")
                checkItem("Deverrouille-le")
                checkItem("Mode developpeur actif (Reglages > Confidentialite et securite)")
            }
            .font(.callout).foregroundStyle(.secondary)
            .padding(16)
            .background(.white.opacity(0.03), in: RoundedRectangle(cornerRadius: 12))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(40)
    }

    private func checkItem(_ text: String) -> some View {
        HStack(spacing: 10) {
            Image(systemName: "circle.dotted").foregroundStyle(Color.accentBlue.opacity(0.7))
            Text(text)
        }
    }
}
