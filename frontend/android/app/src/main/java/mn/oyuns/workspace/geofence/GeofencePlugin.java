package mn.oyuns.workspace.geofence;

import android.Manifest;
import android.annotation.SuppressLint;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;

import androidx.activity.result.ActivityResult;

import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.ActivityCallback;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

import org.json.JSONObject;

/**
 * Web-layer bridge to the geofence layer. The web layer hands over the device
 * credential once; from then on receivers and the upload worker run on their
 * own, also when the app is closed.
 */
@CapacitorPlugin(
    name = "Geofence",
    permissions = {
        @Permission(alias = GeofencePlugin.LOCATION, strings = { Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION }),
        @Permission(alias = GeofencePlugin.BACKGROUND, strings = { Manifest.permission.ACCESS_BACKGROUND_LOCATION })
    }
)
public class GeofencePlugin extends Plugin {
    static final String LOCATION = "location";
    static final String BACKGROUND = "background";

    /** Battery managers that stop background work unless the user allows it. */
    private static final String[][] VENDOR_SETTINGS = {
        { "com.miui.securitycenter", "com.miui.permcenter.autostart.AutoStartManagementActivity" },
        { "com.huawei.systemmanager", "com.huawei.systemmanager.startupmgr.ui.StartupNormalAppListActivity" },
        { "com.huawei.systemmanager", "com.huawei.systemmanager.optimize.process.ProtectActivity" },
        { "com.hihonor.systemmanager", "com.hihonor.systemmanager.startupmgr.ui.StartupNormalAppListActivity" },
        { "com.coloros.safecenter", "com.coloros.safecenter.permission.startup.StartupAppListActivity" },
        { "com.oppo.safe", "com.oppo.safe.permission.startup.StartupAppListActivity" },
        { "com.oplus.battery", "com.oplus.powermanager.fuelgaue.PowerUsageModelActivity" },
        { "com.vivo.permissionmanager", "com.vivo.permissionmanager.activity.BgStartUpManagerActivity" },
        { "com.iqoo.secure", "com.iqoo.secure.ui.phoneoptimize.AddWhiteListActivity" },
        { "com.samsung.android.lool", "com.samsung.android.sm.battery.ui.BatteryActivity" },
        { "com.oneplus.security", "com.oneplus.security.chainlaunch.view.ChainLaunchAppListActivity" },
        { "com.asus.mobilemanager", "com.asus.mobilemanager.autostart.AutoStartActivity" },
        { "com.transsion.phonemanager", "com.itel.autobootmanager.activity.AutoBootMgrActivity" },
    };

    private JSObject status() {
        Context context = getContext();
        JSObject status = new JSObject();
        boolean prompt = getPermissionState(LOCATION) == PermissionState.PROMPT || getPermissionState(LOCATION) == PermissionState.PROMPT_WITH_RATIONALE;
        status.put("enrolled", GeofenceStore.enrolled(context));
        status.put("permission", !GeofenceRegistrar.hasAnyLocation(context) && prompt ? "prompt" : GeofenceRegistrar.permission(context));
        status.put("accuracy", GeofenceRegistrar.hasFineLocation(context) ? "precise" : "approximate");
        status.put("monitoring", GeofenceStore.enrolled(context) && !"off".equals(GeofenceStore.mode(context)) && GeofenceRegistrar.hasBackgroundLocation(context) && GeofenceRegistrar.hasFineLocation(context));
        status.put("regions", GeofenceStore.sites(context).length());
        status.put("pendingEvents", GeofenceStore.pending(context).length());
        status.put("batteryUnrestricted", GeofenceRegistrar.batteryUnrestricted(context));
        status.put("mode", GeofenceStore.mode(context));
        String lastUpload = GeofenceStore.lastUpload(context);
        String lastError = GeofenceStore.lastError(context);
        status.put("lastUploadAt", lastUpload == null ? JSONObject.NULL : lastUpload);
        status.put("lastError", lastError == null ? JSONObject.NULL : lastError);
        return status;
    }

    @PluginMethod
    public void getStatus(PluginCall call) {
        call.resolve(status());
    }

    /** Foreground location first; Android only offers "all the time" afterwards. */
    @PluginMethod
    @Override
    public void requestPermissions(PluginCall call) {
        if (!GeofenceRegistrar.hasFineLocation(getContext())) {
            requestPermissionForAlias(LOCATION, call, "locationResult");
        } else {
            requestBackground(call);
        }
    }

    @PermissionCallback
    private void locationResult(PluginCall call) {
        if (GeofenceRegistrar.hasAnyLocation(getContext())) requestBackground(call);
        else call.resolve(status());
    }

    private void requestBackground(PluginCall call) {
        boolean wanted = Boolean.TRUE.equals(call.getBoolean("background", true));
        if (wanted && Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q && !GeofenceRegistrar.hasBackgroundLocation(getContext())) {
            requestPermissionForAlias(BACKGROUND, call, "backgroundResult");
        } else {
            call.resolve(status());
        }
    }

    @PermissionCallback
    private void backgroundResult(PluginCall call) {
        if (GeofenceStore.enrolled(getContext())) GeofenceUploadWorker.enqueue(getContext(), true);
        call.resolve(status());
    }

    @PluginMethod
    public void configure(PluginCall call) {
        String apiBaseUrl = call.getString("apiBaseUrl");
        String credential = call.getString("credential");
        if (apiBaseUrl == null || !apiBaseUrl.startsWith("https://") || credential == null || credential.isEmpty()) {
            call.reject("apiBaseUrl (https) and credential are required");
            return;
        }
        try {
            GeofenceStore.configure(getContext(), apiBaseUrl, credential);
        } catch (Exception error) {
            call.reject("Unable to store the device credential", error);
            return;
        }
        GeofenceUploadWorker.schedulePeriodic(getContext());
        GeofenceUploadWorker.enqueue(getContext(), true);
        call.resolve(status());
    }

    @PluginMethod
    public void refresh(PluginCall call) {
        if (GeofenceStore.enrolled(getContext())) {
            GeofenceUploadWorker.schedulePeriodic(getContext());
            GeofenceUploadWorker.enqueue(getContext(), true);
        }
        call.resolve(status());
    }

    @PluginMethod
    public void disable(PluginCall call) {
        new Thread(() -> {
            GeofenceUploadWorker.disable(getContext());
            call.resolve(status());
        }).start();
    }

    /**
     * Ask the system to exempt the app from battery optimisation, so the
     * periodic reconciliation keeps running in Doze.
     */
    @SuppressLint("BatteryLife")
    @PluginMethod
    public void requestBatteryExemption(PluginCall call) {
        if (GeofenceRegistrar.batteryUnrestricted(getContext())) {
            call.resolve(status());
            return;
        }
        Intent intent = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:" + getContext().getPackageName()));
        try {
            startActivityForResult(call, intent, "batteryResult");
        } catch (Exception direct) {
            try {
                startActivityForResult(call, new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS), "batteryResult");
            } catch (Exception list) {
                call.resolve(status());
            }
        }
    }

    @ActivityCallback
    private void batteryResult(PluginCall call, ActivityResult result) {
        if (call != null) call.resolve(status());
    }

    /** Open the manufacturer's auto-start / background screen when there is one. */
    @PluginMethod
    public void openBackgroundSettings(PluginCall call) {
        JSObject result = new JSObject();
        for (String[] target : VENDOR_SETTINGS) {
            try {
                Intent intent = new Intent().setComponent(new ComponentName(target[0], target[1])).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                getContext().startActivity(intent);
                result.put("opened", true);
                result.put("vendor", target[0]);
                call.resolve(result);
                return;
            } catch (Exception ignored) {
                // Not this manufacturer (or the screen moved): try the next one.
            }
        }
        result.put("opened", openAppDetails());
        result.put("vendor", JSONObject.NULL);
        call.resolve(result);
    }

    @PluginMethod
    public void openSettings(PluginCall call) {
        JSObject result = new JSObject();
        result.put("opened", openAppDetails());
        call.resolve(result);
    }

    private boolean openAppDetails() {
        try {
            Intent intent = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + getContext().getPackageName())).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(intent);
            return true;
        } catch (Exception error) {
            return false;
        }
    }
}
