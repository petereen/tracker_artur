package mn.oyuns.workspace;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import mn.oyuns.workspace.geofence.GeofenceStore;

/**
 * Tells the web layer what this binary can do, so an OTA bundle running on an
 * older binary hides a feature instead of calling a missing plugin.
 */
@CapacitorPlugin(name = "NativeCapabilities")
public class NativeCapabilitiesPlugin extends Plugin {
    @PluginMethod
    public void getNativeCapabilities(PluginCall call) {
        JSObject result = new JSObject();
        result.put("nativeVersion", GeofenceStore.NATIVE_VERSION);
        result.put("geofence", 1);
        result.put("biometric", 1);
        call.resolve(result);
    }
}
