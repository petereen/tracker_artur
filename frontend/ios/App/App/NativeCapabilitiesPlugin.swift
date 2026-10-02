import Capacitor

/// Tells the web layer what this binary can do, so an OTA bundle running on
/// an older binary hides a feature instead of calling a missing plugin.
@objc(NativeCapabilitiesPlugin)
public class NativeCapabilitiesPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "NativeCapabilitiesPlugin"
    public let jsName = "NativeCapabilities"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "getNativeCapabilities", returnType: CAPPluginReturnPromise)
    ]

    @objc func getNativeCapabilities(_ call: CAPPluginCall) {
        call.resolve([
            "nativeVersion": oyunsNativeVersion,
            "geofence": 1,
            "biometric": 1,
        ])
    }
}
