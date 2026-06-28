import Foundation
import UserNotifications

// Alerte affichee dans l'app (historique) et, si possible, en notification macOS.
struct AlertItem: Identifiable {
    let id = UUID()
    let time: Date
    let kind: String      // cpu | temp | indexing
    let title: String
    let body: String
}

// Encapsule UNUserNotificationCenter. Garde-fou: hors bundle (ex: swift run),
// l'API n'est pas disponible et planterait; on se desactive proprement.
@MainActor
final class NotificationManager {
    static let shared = NotificationManager()

    private let available: Bool
    private var authorized = false

    private init() {
        // Sans bundle identifier (lance hors .app), UNUserNotificationCenter
        // n'est pas utilisable: on neutralise pour ne pas crasher.
        available = Bundle.main.bundleIdentifier != nil
    }

    func requestAuthorization() {
        guard available else { return }
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { granted, _ in
            Task { @MainActor in self.authorized = granted }
        }
    }

    func notify(title: String, body: String, id: String) {
        guard available, authorized else { return }
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        let req = UNNotificationRequest(identifier: id, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(req)
    }
}
