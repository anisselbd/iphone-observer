import Foundation
import Combine
import AppKit

// Pilote le collector Python (sidecar GPL, process separe) et consomme son flux
// WebSocket. Aucun import du moteur: frontiere de licence nette.
@MainActor
final class CollectorClient: ObservableObject {
    @Published var state: String = "demarrage"
    @Published var device: String = "device inconnu"
    @Published var processes: [ProcessRow] = []
    @Published var totals: Totals?
    @Published var battery: Battery?
    @Published var indexing: Indexing?
    @Published var connections: [NetConn] = []
    @Published var netSummary: String = ""
    @Published var logs: [LogLine] = []
    @Published var sidecarManaged: Bool = false
    @Published var lastError: String?
    @Published var timeline: TimelineData?
    @Published var cpuCores: Int = 6
    @Published var paused: Bool = false        // fige la table process pour lire
    @Published var tableIntervalS: Double = 2.0 // cadence de maj de la table

    // Lissage du CPU par process (moyenne mobile) pour stabiliser l'ordre.
    private var smoothedCpu: [Int: Double] = [:]
    private var lastTableEmit: Date = .distantPast

    // Vrai des qu'on a recu au moins un tick: l'app peut afficher le dashboard.
    var hasData: Bool { totals != nil }

    private let host = "127.0.0.1"
    private let port = 8765
    private let session = URLSession(configuration: .default)
    private var task: URLSessionWebSocketTask?
    private var sidecar: Process?
    private var running = false

    // Trace de validation headless (gated par env), sans bruit en usage normal.
    private let debug = ProcessInfo.processInfo.environment["IPHONE_OBSERVER_DEBUG"] != nil
    private var tickCount = 0

    // Chemin du projet pour lancer le sidecar si besoin (surchargeable par env).
    private var projectPath: String {
        ProcessInfo.processInfo.environment["IPHONE_OBSERVER_PROJECT"]
            ?? "\(NSHomeDirectory())/Desktop/Dev/iphone-observer"
    }

    init() {
        // Coupe le sidecar qu'on a lance quand l'app se ferme (pas d'orphelin).
        NotificationCenter.default.addObserver(
            forName: NSApplication.willTerminateNotification, object: nil, queue: .main
        ) { [weak self] _ in
            // La notification est delivree sur la main queue.
            MainActor.assumeIsolated { self?.stop() }
        }
    }

    func start() {
        guard !running else { return }
        running = true
        Task { await ensureCollectorAndConnect() }
        Task { await pollTimeline() }
    }

    private func pollTimeline() async {
        guard let url = URL(string: "http://\(host):\(port)/api/timeline?minutes=10") else { return }
        while running {
            if let (data, _) = try? await session.data(from: url),
               let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let td = TimelineData(obj) {
                timeline = td
            }
            try? await Task.sleep(nanoseconds: 5_000_000_000)
        }
    }

    func stop() {
        running = false
        task?.cancel(with: .goingAway, reason: nil)
        if let sidecar, sidecar.isRunning { sidecar.terminate() }
    }

    private func ensureCollectorAndConnect() async {
        if await !reachable() {
            state = "lancement du collector"
            startSidecar()
            for _ in 0..<40 {
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                if await reachable() { break }
            }
        }
        connect()
    }

    private func reachable() async -> Bool {
        guard let url = URL(string: "http://\(host):\(port)/api/snapshot") else { return false }
        var req = URLRequest(url: url)
        req.timeoutInterval = 3
        do {
            let (_, resp) = try await session.data(for: req)
            return (resp as? HTTPURLResponse)?.statusCode == 200
        } catch {
            return false
        }
    }

    // Localise uv (PATH minimal quand l'app est lancee depuis le Finder).
    private func findUV() -> String? {
        let candidates = [
            "\(NSHomeDirectory())/.local/bin/uv",
            "/opt/homebrew/bin/uv",
            "/usr/local/bin/uv",
        ]
        return candidates.first { FileManager.default.isExecutableFile(atPath: $0) }
    }

    private func startSidecar() {
        guard FileManager.default.fileExists(atPath: projectPath) else {
            state = "projet introuvable"
            lastError = "Collector introuvable a \(projectPath). Definis IPHONE_OBSERVER_PROJECT."
            return
        }
        let p = Process()
        let venvBin = "\(projectPath)/.venv/bin/iphone-observer"
        if FileManager.default.isExecutableFile(atPath: venvBin) {
            // Chemin rapide: binaire du venv directement (demarrage quasi instantane).
            p.executableURL = URL(fileURLWithPath: venvBin)
            p.arguments = ["serve", "--port", "\(port)"]
        } else if let uv = findUV() {
            // Repli: uv resout l'environnement (plus lent a froid).
            p.executableURL = URL(fileURLWithPath: uv)
            p.arguments = ["run", "iphone-observer", "serve", "--port", "\(port)"]
        } else {
            p.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            p.arguments = ["uv", "run", "iphone-observer", "serve", "--port", "\(port)"]
        }
        p.currentDirectoryURL = URL(fileURLWithPath: projectPath)
        do {
            try p.run()
            sidecar = p
            sidecarManaged = true
        } catch {
            state = "echec lancement collector"
            lastError = "Impossible de lancer le collector: \(error.localizedDescription)"
        }
    }

    private func connect() {
        guard running, let url = URL(string: "ws://\(host):\(port)/ws") else { return }
        let t = session.webSocketTask(with: url)
        task = t
        t.resume()
        Task { await receiveLoop() }
    }

    private func receiveLoop() async {
        guard let t = task else { return }
        do {
            while running {
                let message = try await t.receive()
                if case .string(let text) = message { handle(text) }
            }
        } catch {
            guard running else { return }
            state = "reconnexion"
            try? await Task.sleep(nanoseconds: 1_500_000_000)
            connect()
        }
    }

    // MARK: - Parsing de l'enveloppe

    private func handle(_ text: String) {
        guard let data = text.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return }

        if let type = obj["type"] as? String, type == "hello" {
            if let st = obj["state"] as? String { state = st }
            if let events = obj["events"] as? [[String: Any]] { events.forEach(handleEvent) }
            return
        }
        handleEvent(obj)
    }

    private func handleEvent(_ ev: [String: Any]) {
        let source = ev["source"] as? String ?? ""
        let type = ev["type"] as? String ?? ""
        let d = ev["data"] as? [String: Any] ?? [:]
        switch (source, type) {
        case ("sysmontap", "process_tick"): applyTick(d)
        case ("diagnostics", "battery"): battery = parseBattery(d)
        case ("analyzer", "indexing"): indexing = parseIndexing(d)
        case ("networking", "connections"): applyNet(d)
        case ("syslog", "line"): applyLog(d)
        case ("collector", "device"): applyDevice(d)
        case ("collector", "status"):
            if let s = d["state"] as? String { state = s }
        case ("collector", "error"):
            if let m = d["message"] as? String { lastError = m }
        default: break
        }
    }

    private func applyTick(_ d: [String: Any]) {
        if let t = d["totals"] as? [String: Any] {
            totals = Totals(
                aggregateCpu: numD(t["aggregate_cpu"]) ?? 0,
                processCount: numI(t["process_count"]) ?? 0,
                rssMbTotal: numD(t["rss_mb_total"]) ?? 0,
                topName: t["top_name"] as? String ?? "-",
                topCpu: numD(t["top_cpu"]) ?? 0
            )
        }
        let raw = d["processes"] as? [[String: Any]] ?? []
        let alpha = 0.4 // poids de la valeur instantanee (plus bas = plus lisse)
        var present = Set<Int>()
        let rows = raw.compactMap { p -> ProcessRow? in
            guard let pid = numI(p["pid"]) else { return nil }
            present.insert(pid)
            let instant = numD(p["cpu"]) ?? 0
            let prev = smoothedCpu[pid] ?? instant
            let sm = alpha * instant + (1 - alpha) * prev
            smoothedCpu[pid] = sm
            return ProcessRow(
                pid: pid,
                name: p["name"] as? String ?? "pid \(pid)",
                cpu: (sm * 10).rounded() / 10,
                rssMb: numD(p["rss_mb"]) ?? 0,
                threads: numI(p["threads"]) ?? 0
            )
        }
        smoothedCpu = smoothedCpu.filter { present.contains($0.key) }
        lastError = nil // la donnee coule: plus d'erreur a montrer

        // Cadence reduite + pause: la table ne se reordonne pas chaque seconde.
        if !paused, Date().timeIntervalSince(lastTableEmit) >= tableIntervalS {
            processes = Array(rows.sorted { $0.cpu > $1.cpu }.prefix(250))
            lastTableEmit = Date()
        }
        tickCount += 1
        if debug && tickCount % 3 == 1 {
            let cpu = totals.map { Int($0.aggregateCpu) } ?? 0
            let batt = battery?.levelPct.map { "\($0)%" } ?? "?"
            FileHandle.standardError.write(Data(
                "[debug] tick #\(tickCount): \(processes.count) process, CPU \(cpu)%, batt \(batt), idx \(indexing?.state ?? "?"), net \(connections.count) conns\n".utf8
            ))
        }
    }

    private func parseBattery(_ d: [String: Any]) -> Battery {
        var adapter: String?
        if let a = d["adapter"] as? [String: Any] {
            let w = numI(a["watts"])
            let desc = a["description"] as? String
            adapter = [w.map { "\($0) W" }, desc].compactMap { $0 }.joined(separator: " ")
            if adapter?.isEmpty == true { adapter = "branche" }
        }
        return Battery(
            levelPct: numI(d["level_pct"]),
            isCharging: d["is_charging"] as? Bool ?? false,
            externalConnected: d["external_connected"] as? Bool ?? false,
            fullyCharged: d["fully_charged"] as? Bool ?? false,
            temperatureC: numD(d["temperature_c"]),
            voltageV: numD(d["voltage_v"]),
            amperageMa: numI(d["amperage_ma"]),
            cycleCount: numI(d["cycle_count"]),
            healthPct: numD(d["health_pct"]),
            fullCapacity: numI(d["full_capacity_mah"]),
            designCapacity: numI(d["design_capacity_mah"]),
            adapter: adapter
        )
    }

    private func parseIndexing(_ d: [String: Any]) -> Indexing {
        Indexing(
            state: d["state"] as? String ?? "unknown",
            activeNow: d["active_now"] as? Bool ?? false,
            activeCpu: numD(d["active_cpu"]) ?? 0,
            quietForS: numI(d["quiet_for_s"]) ?? 0
        )
    }

    private func applyNet(_ d: [String: Any]) {
        let raw = d["connections"] as? [[String: Any]] ?? []
        connections = raw.compactMap { c -> NetConn? in
            guard let serial = numI(c["serial"]) else { return nil }
            let addr = c["remote_addr"] as? String
            let port = numI(c["remote_port"])
            let remote = addr != nil ? "\(addr!):\(port ?? 0)" : "n/d"
            return NetConn(
                serial: serial,
                pid: numI(c["pid"]) ?? -1,
                iface: c["iface"] as? String ?? "?",
                remote: remote,
                rxRate: numI(c["rx_rate"]) ?? 0,
                txRate: numI(c["tx_rate"]) ?? 0,
                rttMs: numD(c["rtt_ms"]),
                total: (numI(c["rx_bytes"]) ?? 0) + (numI(c["tx_bytes"]) ?? 0)
            )
        }
        if let t = d["totals"] as? [String: Any] {
            let count = numI(t["count"]) ?? 0
            let rx = numI(t["rx_rate"]) ?? 0
            let tx = numI(t["tx_rate"]) ?? 0
            netSummary = "\(count) connexions, down \(formatRate(rx)), up \(formatRate(tx))"
        }
    }

    private func applyLog(_ d: [String: Any]) {
        let line = LogLine(
            time: d["time"] as? String ?? "",
            process: d["process"] as? String ?? "?",
            level: d["level"] as? String ?? "",
            message: d["message"] as? String ?? ""
        )
        logs.append(line)
        if logs.count > 200 { logs.removeFirst(logs.count - 200) }
    }

    private func applyDevice(_ d: [String: Any]) {
        let name = d["name"] as? String ?? "iPhone"
        let model = d["model"] as? String ?? ""
        let ios = d["ios"] as? String ?? ""
        let transport = d["transport"] as? String ?? ""
        device = "\(name) (\(model), iOS \(ios), \(transport))"
        if let cores = numI(d["cpu_cores"]), cores > 0 { cpuCores = cores }
    }

    // MARK: - Helpers

    private func numD(_ v: Any?) -> Double? { (v as? NSNumber)?.doubleValue }
    private func numI(_ v: Any?) -> Int? { (v as? NSNumber)?.intValue }
}

func formatRate(_ bps: Int) -> String {
    if bps >= 1_000_000 { return String(format: "%.1f Mo/s", Double(bps) / 1_000_000) }
    if bps >= 1_000 { return String(format: "%.1f Ko/s", Double(bps) / 1_000) }
    return "\(bps) o/s"
}

func formatBytes(_ b: Int) -> String {
    if b >= 1_000_000 { return String(format: "%.1f Mo", Double(b) / 1_000_000) }
    if b >= 1_000 { return String(format: "%.1f Ko", Double(b) / 1_000) }
    return "\(b) o"
}
