package mn.oyuns.workspace.geofence;

import android.annotation.SuppressLint;
import android.content.Context;
import android.content.pm.PackageInfo;
import android.location.Location;

import androidx.annotation.NonNull;
import androidx.work.Constraints;
import androidx.work.Data;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

import com.google.android.gms.location.CurrentLocationRequest;
import com.google.android.gms.location.LocationServices;
import com.google.android.gms.location.Priority;
import com.google.android.gms.tasks.Tasks;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.TimeUnit;

/**
 * Sends queued geofence events to the OYUNS API with the device credential.
 * With {@code snapshot} it first re-registers the geofences and reports
 * whether the phone is inside a site, which repairs a transition the system
 * did not deliver. A periodic run every 15 minutes keeps doing that on phones
 * whose battery manager stops background work.
 */
public class GeofenceUploadWorker extends Worker {
    private static final String SNAPSHOT = "snapshot";
    private static final String UPLOAD_WORK = "oyuns-geofence-upload";
    private static final String SNAPSHOT_WORK = "oyuns-geofence-snapshot";
    private static final String PERIODIC_WORK = "oyuns-geofence-periodic";
    private static final int BATCH = 50;

    public GeofenceUploadWorker(@NonNull Context context, @NonNull WorkerParameters parameters) {
        super(context, parameters);
    }

    private static Constraints online() {
        return new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build();
    }

    public static void enqueue(Context context, boolean snapshot) {
        OneTimeWorkRequest request = new OneTimeWorkRequest.Builder(GeofenceUploadWorker.class)
            .setConstraints(online())
            .setInputData(new Data.Builder().putBoolean(SNAPSHOT, snapshot).build())
            .build();
        // A transition must not be lost behind a running upload: append it.
        WorkManager.getInstance(context.getApplicationContext())
            .enqueueUniqueWork(snapshot ? SNAPSHOT_WORK : UPLOAD_WORK, snapshot ? ExistingWorkPolicy.REPLACE : ExistingWorkPolicy.APPEND_OR_REPLACE, request);
    }

    public static void schedulePeriodic(Context context) {
        PeriodicWorkRequest request = new PeriodicWorkRequest.Builder(GeofenceUploadWorker.class, 15, TimeUnit.MINUTES)
            .setConstraints(online())
            .setInputData(new Data.Builder().putBoolean(SNAPSHOT, true).build())
            .build();
        WorkManager.getInstance(context.getApplicationContext()).enqueueUniquePeriodicWork(PERIODIC_WORK, ExistingPeriodicWorkPolicy.KEEP, request);
    }

    public static void cancelAll(Context context) {
        WorkManager manager = WorkManager.getInstance(context.getApplicationContext());
        manager.cancelUniqueWork(PERIODIC_WORK);
        manager.cancelUniqueWork(SNAPSHOT_WORK);
        manager.cancelUniqueWork(UPLOAD_WORK);
    }

    /** Stop everything on this phone: consent withdrawn or device replaced. */
    public static void disable(Context context) {
        GeofenceRegistrar.unregister(context);
        cancelAll(context);
        GeofenceStore.clear(context);
    }

    @NonNull
    @Override
    public Result doWork() {
        Context context = getApplicationContext();
        if (!GeofenceStore.enrolled(context)) return Result.success();
        try {
            if (getInputData().getBoolean(SNAPSHOT, false)) {
                Response sites = request(context, "GET", "/v1/mobile/geofences", null);
                if (sites.revoked()) return revoked(context);
                if (sites.ok()) GeofenceStore.saveServerPayload(context, sites.body);
                GeofenceRegistrar.register(context);
                if (!"off".equals(GeofenceStore.mode(context))) GeofenceRegistrar.enqueueSnapshot(context, currentLocation(context));
            }
            return upload(context);
        } catch (Exception error) {
            GeofenceStore.failed(context, error.getClass().getSimpleName());
            return getRunAttemptCount() < 8 ? Result.retry() : Result.failure();
        }
    }

    private Result upload(Context context) throws Exception {
        while (true) {
            JSONArray pending = GeofenceStore.pending(context);
            JSONArray batch = new JSONArray();
            for (int index = 0; index < Math.min(pending.length(), BATCH); index++) batch.put(pending.get(index));
            JSONObject body = new JSONObject();
            body.put("events", batch);
            body.put("state", state(context));
            Response response = request(context, "POST", "/v1/mobile/geo-events", body);
            if (response.revoked()) return revoked(context);
            if (!response.ok()) {
                GeofenceStore.failed(context, "http_" + response.status);
                return getRunAttemptCount() < 8 ? Result.retry() : Result.failure();
            }
            GeofenceStore.removeSent(context, batch);
            GeofenceStore.uploaded(context, GeofenceRegistrar.timestamp(System.currentTimeMillis()));
            String before = GeofenceStore.sites(context).toString() + GeofenceStore.mode(context);
            GeofenceStore.saveServerPayload(context, response.body);
            // The administrator moved a site or changed the mode.
            if (!before.equals(GeofenceStore.sites(context).toString() + GeofenceStore.mode(context))) GeofenceRegistrar.register(context);
            if (GeofenceStore.pending(context).length() == 0) return Result.success();
        }
    }

    private Result revoked(Context context) {
        disable(context);
        GeofenceStore.failed(context, "device_revoked");
        return Result.success();
    }

    private static JSONObject state(Context context) throws Exception {
        JSONObject state = new JSONObject();
        state.put("location_permission", GeofenceRegistrar.permission(context));
        state.put("location_accuracy", GeofenceRegistrar.hasFineLocation(context) ? "precise" : "approximate");
        state.put("battery_unrestricted", GeofenceRegistrar.batteryUnrestricted(context));
        state.put("native_version", GeofenceStore.NATIVE_VERSION);
        PackageInfo info = context.getPackageManager().getPackageInfo(context.getPackageName(), 0);
        state.put("app_version", info.versionName == null ? "" : info.versionName);
        return state;
    }

    @SuppressLint("MissingPermission")
    private static Location currentLocation(Context context) {
        if (!GeofenceRegistrar.hasAnyLocation(context) || !GeofenceRegistrar.hasBackgroundLocation(context)) return null;
        try {
            CurrentLocationRequest request = new CurrentLocationRequest.Builder()
                .setPriority(Priority.PRIORITY_BALANCED_POWER_ACCURACY)
                .setMaxUpdateAgeMillis(60_000)
                .setDurationMillis(20_000)
                .build();
            return Tasks.await(LocationServices.getFusedLocationProviderClient(context).getCurrentLocation(request, null), 25, TimeUnit.SECONDS);
        } catch (Exception error) {
            return null;
        }
    }

    private static final class Response {
        final int status;
        final JSONObject body;

        Response(int status, JSONObject body) {
            this.status = status;
            this.body = body;
        }

        boolean ok() {
            return status == 200 && body != null;
        }

        boolean revoked() {
            return status == 401;
        }
    }

    private static Response request(Context context, String method, String path, JSONObject body) throws Exception {
        String base = GeofenceStore.apiBaseUrl(context);
        String credential = GeofenceStore.credential(context);
        if (base == null || credential == null || !base.startsWith("https://")) return new Response(401, null);
        HttpURLConnection connection = (HttpURLConnection) new URL(base + path).openConnection();
        try {
            connection.setRequestMethod(method);
            connection.setConnectTimeout(15_000);
            connection.setReadTimeout(25_000);
            connection.setRequestProperty("Authorization", "Device " + credential);
            connection.setRequestProperty("Accept", "application/json");
            if (body != null) {
                connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type", "application/json");
                try (OutputStream output = connection.getOutputStream()) {
                    output.write(body.toString().getBytes(StandardCharsets.UTF_8));
                }
            }
            int status = connection.getResponseCode();
            JSONObject payload = null;
            if (status == 200) {
                try (InputStream input = connection.getInputStream()) {
                    ByteArrayOutputStream buffer = new ByteArrayOutputStream();
                    byte[] chunk = new byte[4096];
                    int read;
                    while ((read = input.read(chunk)) != -1) buffer.write(chunk, 0, read);
                    payload = new JSONObject(buffer.toString("UTF-8"));
                }
            }
            return new Response(status, payload);
        } finally {
            connection.disconnect();
        }
    }
}
