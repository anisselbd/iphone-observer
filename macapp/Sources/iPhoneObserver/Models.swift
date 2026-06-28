import Foundation

// Modeles natifs alimentes depuis l'enveloppe d'events du collector.

struct ProcessRow: Identifiable {
    let pid: Int
    let name: String
    let cpu: Double
    let rssMb: Double
    let threads: Int
    var id: Int { pid }
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
