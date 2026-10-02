import Capacitor
import LocalAuthentication

/// Face ID / Touch ID prompt for the app lock and for confirming consent.
@objc(BiometricAuthPlugin)
public class BiometricAuthPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "BiometricAuthPlugin"
    public let jsName = "BiometricAuth"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "isAvailable", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "authenticate", returnType: CAPPluginReturnPromise),
    ]

    @objc func isAvailable(_ call: CAPPluginCall) {
        let context = LAContext()
        var error: NSError?
        let biometric = context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &error)
        let secure = LAContext().canEvaluatePolicy(.deviceOwnerAuthentication, error: nil)
        var type = "none"
        if biometric {
            switch context.biometryType {
            case .faceID: type = "face"
            case .touchID: type = "fingerprint"
            default: type = "biometric"
            }
        }
        call.resolve(["available": biometric, "deviceSecure": secure, "biometryType": type])
    }

    @objc func authenticate(_ call: CAPPluginCall) {
        let reason = call.getString("reason") ?? "OYUNS"
        // With the passcode fallback a user whose face or finger is not
        // recognised is never locked out of the app.
        let allowDeviceCredential = call.getBool("allowDeviceCredential") ?? true
        let context = LAContext()
        let policy: LAPolicy = allowDeviceCredential ? .deviceOwnerAuthentication : .deviceOwnerAuthenticationWithBiometrics
        var error: NSError?
        guard context.canEvaluatePolicy(policy, error: &error) else {
            call.reject("Biometric authentication is not available", "unavailable", error)
            return
        }
        context.evaluatePolicy(policy, localizedReason: reason) { success, failure in
            if success {
                call.resolve(["success": true])
                return
            }
            let code = (failure as? LAError)?.code
            let cancelled = code == .userCancel || code == .appCancel || code == .systemCancel
            call.reject("Authentication failed", cancelled ? "cancelled" : "failed", failure)
        }
    }
}
