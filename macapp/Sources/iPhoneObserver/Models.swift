import Foundation

// Modeles natifs alimentes depuis l'enveloppe d'events du collector.

struct ProcessRow: Identifiable {
    let pid: Int
    let name: String
    let cpu: Double
    let rssMb: Double
    let threads: Int
    let power: Double   // score energie relatif (powerScore device), sans unite
    var id: Int { pid }
}

// Echantillon d'historique par process, accumule en memoire a chaque tick (1 Hz)
// a partir de la liste complete (pas seulement le top affiche). Couvre la session
// courante de l'app.
struct ProcSample: Identifiable {
    let t: Double
    let cpu: Double
    let rss: Double
    let power: Double
    var id: Double { t }
}

// GPU et FPS systeme (channel Instruments OpenGL). available=false si le service
// a refuse de demarrer (on l'affiche tel quel, sans inventer de valeur).
struct GraphicsStats {
    let gpuUtil: Double?
    let rendererUtil: Double?
    let tilerUtil: Double?
    let fps: Double?
    let gpuMemInuseMb: Double?
    let available: Bool
    let reason: String?
}

struct Totals {
    let aggregateCpu: Double
    let processCount: Int
    let rssMbTotal: Double
    let topName: String
    let topCpu: Double
}

struct Battery {
    let levelPct: Int?
    let isCharging: Bool
    let externalConnected: Bool
    let fullyCharged: Bool
    let temperatureC: Double?
    let voltageV: Double?
    let amperageMa: Int?
    let cycleCount: Int?
    let healthPct: Double?
    let fullCapacity: Int?
    let designCapacity: Int?
    let adapter: String?

    var stateLabel: String {
        if isCharging { return "en charge" }
        if fullyCharged && externalConnected { return "plein (branche)" }
        if externalConnected { return "branche" }
        return "sur batterie"
    }
}

struct Indexing {
    let state: String        // indexing | idle | unknown
    let activeNow: Bool
    let activeCpu: Double
    let quietForS: Int

    var label: String {
        switch state {
        case "indexing": return activeNow ? "Indexation en cours" : "Indexation (refroidissement)"
        case "idle": return "Indexation terminee"
        default: return "Indexation: evaluation"
        }
    }
}

struct NetConn: Identifiable {
    let serial: Int
    let pid: Int
    let iface: String
    let remote: String
    let rxRate: Int
    let txRate: Int
    let rttMs: Double?
    let total: Int
    var id: Int { serial }
}

struct LogLine: Identifiable {
    let id = UUID()
    let time: String
    let process: String
    let level: String
    let message: String
}

struct Memory {
    let totalMb: Int
    let usedMb: Int
    let freeMb: Int
    let compressedMb: Int
    let swapMb: Int?
    var totalGo: Double { Double(totalMb) / 1000 }
    var usedGo: Double { Double(usedMb) / 1000 }
    var fraction: Double { totalMb > 0 ? Double(usedMb) / Double(totalMb) : 0 }
}

// Metriques systeme etendues issues de l'echantillon System de sysmontap.
// Les debits disque/reseau sont calcules cote collector (delta de compteurs).
struct SystemStats {
    let threads: Int?
    let diskReadBps: Int?
    let diskWriteBps: Int?
    let diskReadOps: Int?
    let diskWriteOps: Int?
    let netInBps: Int?
    let netOutBps: Int?
    let netInPps: Int?
    let netOutPps: Int?
}

struct TimelinePoint {
    let t: Double
    let v: Double
}

struct TimelineData {
    let since: Double
    let until: Double
    let minutes: Double
    let totalRows: Int
    let cpu: [TimelinePoint]
    let temp: [TimelinePoint]
    let net: [TimelinePoint]
    let diskRead: [TimelinePoint]
    let diskWrite: [TimelinePoint]
    let swap: [TimelinePoint]
    let gpu: [TimelinePoint]
    let fps: [TimelinePoint]
    let indexing: [(t: Double, state: String)]
    let errors: [Double]

    init?(_ o: [String: Any]) {
        guard (o["available"] as? Bool) == true,
              let s = o["series"] as? [String: Any] else { return nil }

        func series(_ key: String) -> [TimelinePoint] {
            guard let arr = s[key] as? [Any] else { return [] }
            return arr.compactMap { row in
                guard let p = row as? [Any], p.count >= 2,
                      let t = (p[0] as? NSNumber)?.doubleValue,
                      let v = (p[1] as? NSNumber)?.doubleValue else { return nil }
                return TimelinePoint(t: t, v: v)
            }
        }

        let rx = series("net_rx_rate"), tx = series("net_tx_rate")
        var netPts: [TimelinePoint] = []
        for i in 0..<min(rx.count, tx.count) {
            netPts.append(TimelinePoint(t: rx[i].t, v: rx[i].v + tx[i].v))
        }

        since = (o["since"] as? NSNumber)?.doubleValue ?? 0
        until = (o["until"] as? NSNumber)?.doubleValue ?? 0
        minutes = (o["minutes"] as? NSNumber)?.doubleValue ?? 10
        totalRows = (o["total_rows"] as? NSNumber)?.intValue ?? 0
        cpu = series("cpu_aggregate")
        temp = series("battery_temp_c")
        net = netPts
        diskRead = series("disk_read_bps")
        diskWrite = series("disk_write_bps")
        swap = series("swap_mb")
        gpu = series("gpu_util")
        fps = series("fps")
        indexing = (o["indexing"] as? [Any] ?? []).compactMap { row in
            guard let e = row as? [Any], e.count >= 2,
                  let t = (e[0] as? NSNumber)?.doubleValue,
                  let st = e[1] as? String else { return nil }
            return (t, st)
        }
        errors = (o["errors"] as? [Any] ?? []).compactMap { row in
            guard let e = row as? [Any], e.count >= 1,
                  let t = (e[0] as? NSNumber)?.doubleValue else { return nil }
            return t
        }
    }
}
