package mn.oyuns.workspace.geofence;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.location.Location;
import android.os.Build;
import android.os.PowerManager;

import androidx.core.content.ContextCompat;

import com.google.android.gms.location.Geofence;
import com.google.android.gms.location.GeofencingClient;
import com.google.android.gms.location.GeofencingRequest;
import com.google.android.gms.location.LocationServices;
import com.google.android.gms.tasks.Tasks;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.TimeZone;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

/** Registers the office geofences with Google Play services and builds events. */
public final class GeofenceRegistrar {
    /** Play services does not detect smaller areas reliably. */
    private static final float MIN_RADIUS_METERS = 100f;
    private static final int MAX_SITES = 20;

    private GeofenceRegistrar() {}

    public static boolean hasFineLocation(Context context) {
        return ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED;
    }

    public static boolean hasAnyLocation(Context context) {
        return hasFineLocation(context)
            || ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED;
    }

    public static boolean hasBackgroundLocation(Context context) {
        if (!hasAnyLocation(context)) return false;
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return true;
        return ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_BACKGROUND_LOCATION) == PackageManager.PERMISSION_GRANTED;
    }

    public static boolean batteryUnrestricted(Context context) {
        PowerManager power = (PowerManager) context.getSystemService(Context.POWER_SERVICE);
        return power != null && power.isIgnoringBatteryOptimizations(context.getPackageName());
    }

    public static String permission(Context context) {
        if (!hasAnyLocation(context)) return "denied";
        return hasBackgroundLocation(context) ? "always" : "when_in_use";
    }

    private static PendingIntent pendingIntent(Context context) {
        Intent intent = new Intent(context, GeofenceBroadcastReceiver.class);
        // Play services fills in the transition, so the intent must be mutable.
        int flags = PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S ? PendingIntent.FLAG_MUTABLE : 0);
        return PendingIntent.getBroadcast(context, 0, intent, flags);
    }

    /**
     * (Re)register the stored sites. Safe to repeat: after a reboot, an app
     * update or a Play services reset the registrations are gone. There is no
     * initial trigger: whether the phone is inside right now is reported as a
     * snapshot, which the server treats more carefully than a real arrival.
     */
    @SuppressLint("MissingPermission")
    public static void register(Context context) throws Exception {
        Context app = context.getApplicationContext();
        GeofencingClient client = LocationServices.getGeofencingClient(app);
        JSONArray sites = GeofenceStore.sites(app);
        if (!GeofenceStore.enrolled(app) || "off".equals(GeofenceStore.mode(app)) || sites.length() == 0 || !hasFineLocation(app) || !hasBackgroundLocation(app)) {
            Tasks.await(client.removeGeofences(pendingIntent(app)), 20, TimeUnit.SECONDS);
            return;
        }
        List<Geofence> geofences = new ArrayList<>();
        for (int index = 0; index < Math.min(sites.length(), MAX_SITES); index++) {
            JSONObject site = sites.optJSONObject(index);
            if (site == null || site.optString("id").isEmpty()) continue;
            geofences.add(new Geofence.Builder()
                .setRequestId(site.optString("id"))
                .setCircularRegion(site.optDouble("latitude"), site.optDouble("longitude"), Math.max(MIN_RADIUS_METERS, (float) site.optDouble("radius_meters", 150)))
                .setExpirationDuration(Geofence.NEVER_EXPIRE)
                .setTransitionTypes(Geofence.GEOFENCE_TRANSITION_ENTER | Geofence.GEOFENCE_TRANSITION_EXIT)
                .setNotificationResponsiveness(0)
                .build());
        }
        if (geofences.isEmpty()) return;
        GeofencingRequest request = new GeofencingRequest.Builder().setInitialTrigger(0).addGeofences(geofences).build();
        Tasks.await(client.removeGeofences(pendingIntent(app)), 20, TimeUnit.SECONDS);
        Tasks.await(client.addGeofences(request, pendingIntent(app)), 20, TimeUnit.SECONDS);
    }

    public static void unregister(Context context) {
        try {
            Tasks.await(LocationServices.getGeofencingClient(context.getApplicationContext()).removeGeofences(pendingIntent(context.getApplicationContext())), 20, TimeUnit.SECONDS);
        } catch (Exception ignored) {
            // Nothing registered, or Play services is unavailable.
        }
    }

    public static String timestamp(long millis) {
        SimpleDateFormat format = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US);
        format.setTimeZone(TimeZone.getTimeZone("UTC"));
        return format.format(new Date(millis));
    }

    public static boolean isMock(Location location) {
        if (location == null) return false;
        return Build.VERSION.SDK_INT >= Build.VERSION_CODES.S ? location.isMock() : location.isFromMockProvider();
    }

    /** An event for the server. Coordinates are sent for snapshots only. */
    public static JSONObject event(String kind, String siteId, Location location, boolean withPosition) throws JSONException {
        JSONObject event = new JSONObject();
        event.put("client_event_id", UUID.randomUUID().toString());
        event.put("kind", kind);
        event.put("site_id", siteId);
        event.put("occurred_at", timestamp(System.currentTimeMillis()));
        event.put("is_mock", isMock(location));
        if (location != null && location.hasAccuracy()) {
            event.put("accuracy_meters", location.getAccuracy());
            if (withPosition) {
                event.put("latitude", location.getLatitude());
                event.put("longitude", location.getLongitude());
            }
        }
        return event;
    }

    /** One inside/outside snapshot per site for a fresh position. */
    public static void enqueueSnapshot(Context context, Location location) throws JSONException {
        if (location == null) return;
        JSONArray sites = GeofenceStore.sites(context);
        float[] distance = new float[1];
        for (int index = 0; index < Math.min(sites.length(), MAX_SITES); index++) {
            JSONObject site = sites.optJSONObject(index);
            if (site == null) continue;
            Location.distanceBetween(location.getLatitude(), location.getLongitude(), site.optDouble("latitude"), site.optDouble("longitude"), distance);
            float radius = Math.max(MIN_RADIUS_METERS, (float) site.optDouble("radius_meters", 150));
            float accuracy = location.hasAccuracy() ? location.getAccuracy() : 0f;
            // Undecided near the edge: say nothing rather than guess.
            if (distance[0] + accuracy <= radius) {
                GeofenceStore.enqueue(context, event("state_inside", site.optString("id"), location, true));
            } else if (distance[0] - accuracy > radius) {
                GeofenceStore.enqueue(context, event("state_outside", site.optString("id"), location, true));
            }
        }
    }
}
