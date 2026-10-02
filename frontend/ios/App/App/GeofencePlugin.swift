import Capacitor
import UIKit

/// Web-layer bridge to `GeofenceEngine`.
@objc(GeofencePlugin)
public class GeofencePlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "GeofencePlugin"
    public let jsName = "Geofence"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "getStatus", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "requestPermissions", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "configure", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "refresh", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "disable", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "requestBatteryExemption", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "openBackgroundSettings", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "openSettings", returnType: CAPPluginReturnPromise),
    ]

    @objc func getStatus(_ call: CAPPluginCall) {
        DispatchQueue.main.async { call.resolve(GeofenceEngine.shared.status()) }
    }

    @objc override public func requestPermissions(_ call: CAPPluginCall) {
        let background = call.getBool("background") ?? true
        DispatchQueue.main.async {
            GeofenceEngine.shared.requestPermission(background: background) { _ in
                call.resolve(GeofenceEngine.shared.status())
            }
        }
    }

    @objc func configure(_ call: CAPPluginCall) {
        guard let apiBaseUrl = call.getString("apiBaseUrl"), apiBaseUrl.hasPrefix("https://"),
              let credential = call.getString("credential"), !credential.isEmpty else {
            call.reject("apiBaseUrl (https) and credential are required")
            return
        }
        DispatchQueue.main.async {
            GeofenceEngine.shared.configure(apiBaseUrl: apiBaseUrl, credential: credential)
            GeofenceEngine.shared.refresh { _ in call.resolve(GeofenceEngine.shared.status()) }
        }
    }

    @objc func refresh(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            GeofenceEngine.shared.refresh { _ in call.resolve(GeofenceEngine.shared.status()) }
        }
    }

    @objc func disable(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            GeofenceEngine.shared.disable()
            call.resolve(GeofenceEngine.shared.status())
        }
    }

    /// iOS has no per-app battery exemption; kept so the web layer has one API.
    @objc func requestBatteryExemption(_ call: CAPPluginCall) {
        call.resolve(["batteryUnrestricted": true])
    }

    @objc func openBackgroundSettings(_ call: CAPPluginCall) {
        call.resolve(["opened": false])
    }

    @objc func openSettings(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            guard let url = URL(string: UIApplication.openSettingsURLString) else {
                call.resolve(["opened": false])
                return
            }
            UIApplication.shared.open(url) { opened in call.resolve(["opened": opened]) }
        }
    }
}
