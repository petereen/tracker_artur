import CoreLocation
import Foundation
import Security
import UIKit

/// Build number of the native layer. Bump it whenever a store binary adds a
/// native capability, so the web layer and the OTA server can tell binaries apart.
let oyunsNativeVersion = 2

/// Registers the office geofences with iOS and reports transitions to the
/// OYUNS API. It makes no decision about work time: the server does.
///
/// iOS relaunches the app in the background for a region event while the web
/// layer is not loaded, so this object talks to the API itself, with a device
/// credential kept in the Keychain (never the user's session).
final class GeofenceEngine: NSObject, CLLocationManagerDelegate {
    static let shared = GeofenceEngine()

    private let manager = CLLocationManager()
    private let defaults = UserDefaults.standard
    private let queue = DispatchQueue(label: "mn.oyuns.workspace.geofence")
    private var snapshotRegions = Set<String>()
    private var uploading = false
    private var permissionWaiters: [(String) -> Void] = []

    private enum Key {
        static let apiBaseUrl = "oyuns.geofence.apiBaseUrl"
        static let sites = "oyuns.geofence.sites"
        static let mode = "oyuns.geofence.mode"
        static let pending = "oyuns.geofence.pending"
        static let lastSnapshot = "oyuns.geofence.lastSnapshot"
        static let lastError = "oyuns.geofence.lastError"
        static let lastUpload = "oyuns.geofence.lastUpload"
        static let keychainService = "mn.oyuns.workspace.geofence"
        static let keychainAccount = "device-credential"
    }

    private static let maxPending = 200
    private static let snapshotInterval: TimeInterval = 15 * 60
    private static let freshLocation: TimeInterval = 120

    private let timestamps: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    // MARK: Lifecycle

    /// Called from the app delegate on every launch, including the background
    /// relaunch iOS performs to deliver a region event.
    func start() {
        manager.delegate = self
        manager.pausesLocationUpdatesAutomatically = true
        guard credential != nil else { return }
        if CLLocationManager.significantLocationChangeMonitoringAvailable() {
            manager.startMonitoringSignificantLocationChanges()
        }
        flush()
    }

    // MARK: Called by the plugin

    func configure(apiBaseUrl: String, credential: String) {
        defaults.set(apiBaseUrl, forKey: Key.apiBaseUrl)
        storeCredential(credential)
        defaults.removeObject(forKey: Key.lastError)
        if CLLocationManager.significantLocationChangeMonitoringAvailable() {
            manager.startMonitoringSignificantLocationChanges()
        }
    }

    func disable() {
        stopAllRegions()
        manager.stopMonitoringSignificantLocationChanges()
        storeCredential(nil)
        for key in [Key.sites, Key.mode, Key.pending, Key.lastSnapshot, Key.lastUpload] {
            defaults.removeObject(forKey: key)
        }
    }

    /// Fetch the sites, register them and report whether the phone is inside.
    func refresh(completion: @escaping (Bool) -> Void) {
        guard credential != nil else { completion(false); return }
        request(path: "/v1/mobile/geofences", method: "GET", body: nil) { [weak self] status, payload in
            guard let self = self else { return }
            if status == 200, let payload = payload {
                self.apply(payload: payload)
                self.requestSnapshot()
                completion(true)
            } else {
                completion(false)
            }
        }
    }

    func status() -> [String: Any] {
        return [
            "enrolled": credential != nil,
            "permission": permission(),
            "accuracy": accuracy(),
            "monitoring": !manager.monitoredRegions.isEmpty,
            "regions": manager.monitoredRegions.count,
            "pendingEvents": pending().count,
            "batteryUnrestricted": true,
            "mode": defaults.string(forKey: Key.mode) ?? "off",
            "lastUploadAt": defaults.string(forKey: Key.lastUpload) ?? NSNull(),
            "lastError": defaults.string(forKey: Key.lastError) ?? NSNull(),
        ]
    }

    /// When-in-use first, then "always": iOS only shows the second prompt
    /// after the first one was granted.
    func requestPermission(background: Bool, completion: @escaping (String) -> Void) {
        let current = manager.authorizationStatus
        if current == .notDetermined {
            permissionWaiters.append { [weak self] _ in
                guard let self = self else { return }
                if background && self.manager.authorizationStatus == .authorizedWhenInUse {
                    self.askAlways(completion: completion)
                } else {
                    completion(self.permission())
                }
            }
            manager.requestWhenInUseAuthorization()
        } else if background && current == .authorizedWhenInUse {
            askAlways(completion: completion)
        } else {
            completion(permission())
        }
    }

    private func askAlways(completion: @escaping (String) -> Void) {
        var answered = false
        let finish: (String) -> Void = { value in
            if !answered { answered = true; completion(value) }
        }
        permissionWaiters.append(finish)
        manager.requestAlwaysAuthorization()
        // iOS shows the "always" prompt at most once and reports nothing when
        // it decides not to show it again.
        DispatchQueue.main.asyncAfter(deadline: .now() + 20) { [weak self] in
            guard let self = self else { return }
            self.permissionWaiters.removeAll()
            finish(self.permission())
        }
    }

    // MARK: CLLocationManagerDelegate

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let waiters = permissionWaiters
        permissionWaiters.removeAll()
        let value = permission()
        waiters.forEach { $0(value) }
        if credential != nil { flush() }
    }

    func locationManager(_ manager: CLLocationManager, didEnterRegion region: CLRegion) {
        record(kind: "enter", region: region, withPosition: false)
    }

    func locationManager(_ manager: CLLocationManager, didExitRegion region: CLRegion) {
        record(kind: "exit", region: region, withPosition: false)
    }

    func locationManager(_ manager: CLLocationManager, didDetermineState state: CLRegionState, for region: CLRegion) {
        // Only snapshots we asked for: iOS also calls this on its own.
        guard snapshotRegions.remove(region.identifier) != nil, state != .unknown else { return }
        record(kind: state == .inside ? "state_inside" : "state_outside", region: region, withPosition: true)
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        // A significant location change is the periodic wake-up used to
        // reconcile a transition iOS did not deliver.
        let last = defaults.double(forKey: Key.lastSnapshot)
        if Date().timeIntervalSince1970 - last >= GeofenceEngine.snapshotInterval {
            refresh { _ in }
        } else {
            flush()
        }
    }

    func locationManager(_ manager: CLLocationManager, monitoringDidFailFor region: CLRegion?, withError error: Error) {
        defaults.set("monitoring: \(error.localizedDescription)", forKey: Key.lastError)
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        defaults.set("location: \(error.localizedDescription)", forKey: Key.lastError)
    }

    // MARK: Regions

    private func apply(payload: [String: Any]) {
        let config = payload["config"] as? [String: Any]
        let mode = config?["mode"] as? String ?? "off"
        defaults.set(mode, forKey: Key.mode)
        let sites = (payload["sites"] as? [[String: Any]]) ?? []
        if let encoded = try? JSONSerialization.data(withJSONObject: sites) {
            defaults.set(encoded, forKey: Key.sites)
        }
        guard mode != "off", CLLocationManager.isMonitoringAvailable(for: CLCircularRegion.self) else {
            stopAllRegions()
            return
        }
        var wanted: [String: CLCircularRegion] = [:]
        for site in sites.prefix(20) {
            guard let identifier = site["id"] as? String,
                  let latitude = (site["latitude"] as? NSNumber)?.doubleValue,
                  let longitude = (site["longitude"] as? NSNumber)?.doubleValue,
                  let radius = (site["radius_meters"] as? NSNumber)?.doubleValue else { continue }
            let region = CLCircularRegion(
                center: CLLocationCoordinate2D(latitude: latitude, longitude: longitude),
                // Regions smaller than ~100 m are not detected reliably.
                radius: min(max(radius, 100), manager.maximumRegionMonitoringDistance),
                identifier: identifier
            )
            region.notifyOnEntry = true
            region.notifyOnExit = true
            wanted[identifier] = region
        }
        for region in manager.monitoredRegions {
            let same = (region as? CLCircularRegion).flatMap { current -> Bool? in
                guard let next = wanted[current.identifier] else { return nil }
                return abs(current.center.latitude - next.center.latitude) < 0.000001
                    && abs(current.center.longitude - next.center.longitude) < 0.000001
                    && abs(current.radius - next.radius) < 1
            }
            if same == true {
                wanted.removeValue(forKey: region.identifier)
            } else {
                manager.stopMonitoring(for: region)
            }
        }
        wanted.values.forEach { manager.startMonitoring(for: $0) }
    }

    private func stopAllRegions() {
        manager.monitoredRegions.forEach { manager.stopMonitoring(for: $0) }
    }

    private func requestSnapshot() {
        defaults.set(Date().timeIntervalSince1970, forKey: Key.lastSnapshot)
        // Regions added a moment ago are not ready to be queried yet.
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in
            guard let self = self else { return }
            for region in self.manager.monitoredRegions {
                self.snapshotRegions.insert(region.identifier)
                self.manager.requestState(for: region)
            }
            self.flush()
        }
    }

    // MARK: Events

    private func record(kind: String, region: CLRegion, withPosition: Bool) {
        guard credential != nil, (defaults.string(forKey: Key.mode) ?? "off") != "off" else { return }
        var event: [String: Any] = [
            "client_event_id": UUID().uuidString.lowercased(),
            "kind": kind,
            "site_id": region.identifier,
            "occurred_at": timestamps.string(from: Date()),
            "is_mock": false,
        ]
        if let location = manager.location, abs(location.timestamp.timeIntervalSinceNow) <= GeofenceEngine.freshLocation, location.horizontalAccuracy >= 0 {
            event["accuracy_meters"] = location.horizontalAccuracy
            if let source = location.sourceInformation {
                event["is_mock"] = source.isSimulatedBySoftware
            }
            if withPosition {
                event["latitude"] = location.coordinate.latitude
                event["longitude"] = location.coordinate.longitude
            }
        }
        queue.sync {
            var events = pending()
            events.append(event)
            if events.count > GeofenceEngine.maxPending {
                events.removeFirst(events.count - GeofenceEngine.maxPending)
            }
            savePending(events)
        }
        flush()
    }

    private func pending() -> [[String: Any]] {
        guard let data = defaults.data(forKey: Key.pending),
              let events = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] else { return [] }
        return events
    }

    private func savePending(_ events: [[String: Any]]) {
        if let data = try? JSONSerialization.data(withJSONObject: events) {
            defaults.set(data, forKey: Key.pending)
        }
    }

    /// Send queued events together with the permission snapshot.
    func flush() {
        guard credential != nil else { return }
        var batch: [[String: Any]] = []
        var busy = false
        queue.sync {
            busy = uploading
            if !busy {
                batch = Array(pending().prefix(50))
                uploading = true
            }
        }
        if busy { return }
        var task: UIBackgroundTaskIdentifier = .invalid
        task = UIApplication.shared.beginBackgroundTask(withName: "oyuns.geofence.upload") {
            UIApplication.shared.endBackgroundTask(task)
            task = .invalid
        }
        let body: [String: Any] = [
            "events": batch,
            "state": [
                "location_permission": permission() == "prompt" ? "denied" : permission(),
                "location_accuracy": accuracy(),
                "battery_unrestricted": true,
                "native_version": oyunsNativeVersion,
                "app_version": Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "",
            ],
        ]
        request(path: "/v1/mobile/geo-events", method: "POST", body: body) { [weak self] status, payload in
            guard let self = self else { return }
            var more = false
            self.queue.sync {
                self.uploading = false
                if status == 200 {
                    let sent = Set(batch.compactMap { $0["client_event_id"] as? String })
                    let remaining = self.pending().filter { !sent.contains(($0["client_event_id"] as? String) ?? "") }
                    self.savePending(remaining)
                    more = !remaining.isEmpty
                }
            }
            if status == 200 {
                self.defaults.set(self.timestamps.string(from: Date()), forKey: Key.lastUpload)
                self.defaults.removeObject(forKey: Key.lastError)
                if let payload = payload { self.apply(payload: payload) }
            }
            if task != .invalid {
                UIApplication.shared.endBackgroundTask(task)
                task = .invalid
            }
            if more { self.flush() }
        }
    }

    // MARK: HTTP

    private func request(path: String, method: String, body: [String: Any]?, completion: @escaping (Int, [String: Any]?) -> Void) {
        guard let credential = credential,
              let base = defaults.string(forKey: Key.apiBaseUrl),
              let url = URL(string: base + path), url.scheme == "https" else {
            DispatchQueue.main.async { completion(0, nil) }
            return
        }
        var request = URLRequest(url: url, timeoutInterval: 25)
        request.httpMethod = method
        request.setValue("Device \(credential)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body = body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            let payload = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            DispatchQueue.main.async {
                guard let self = self else { return }
                if status == 401 {
                    // Consent withdrawn or the device was replaced: stop at once.
                    self.disable()
                    self.defaults.set("device_revoked", forKey: Key.lastError)
                } else if status != 200 {
                    self.defaults.set(error?.localizedDescription ?? "http_\(status)", forKey: Key.lastError)
                }
                completion(status, payload)
            }
        }.resume()
    }

    // MARK: Permission

    func permission() -> String {
        switch manager.authorizationStatus {
        case .authorizedAlways: return "always"
        case .authorizedWhenInUse: return "when_in_use"
        case .notDetermined: return "prompt"
        default: return "denied"
        }
    }

    private func accuracy() -> String {
        return manager.accuracyAuthorization == .fullAccuracy ? "precise" : "approximate"
    }

    // MARK: Keychain

    private var credential: String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: Key.keychainService,
            kSecAttrAccount as String: Key.keychainAccount,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess, let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private func storeCredential(_ value: String?) {
        let base: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: Key.keychainService,
            kSecAttrAccount as String: Key.keychainAccount,
        ]
        SecItemDelete(base as CFDictionary)
        guard let value = value, let data = value.data(using: .utf8) else { return }
        var item = base
        item[kSecValueData as String] = data
        // Readable in the background after the first unlock, never synced or
        // restored to another device.
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(item as CFDictionary, nil)
    }
}
