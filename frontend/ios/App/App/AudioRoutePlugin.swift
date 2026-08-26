import AVFoundation
import Capacitor

@objc(AudioRoutePlugin)
public class AudioRoutePlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "AudioRoutePlugin"
    public let jsName = "AudioRoute"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "setRoute", returnType: CAPPluginReturnPromise)
    ]

    @objc func setRoute(_ call: CAPPluginCall) {
        let route = call.getString("route") ?? "default"
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, mode: .voiceChat, options: [.allowBluetooth, .allowBluetoothA2DP])
            try session.setActive(true)
            try session.overrideOutputAudioPort(route == "speaker" ? .speaker : .none)
            call.resolve(["route": route == "speaker" ? "speaker" : "default"])
        } catch {
            call.reject("Unable to change audio route", nil, error)
        }
    }
}
