package mn.oyuns.workspace.geofence;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

import com.google.android.gms.location.Geofence;
import com.google.android.gms.location.GeofencingEvent;

import org.json.JSONException;

/**
 * Receives office geofence transitions, also while the app is not running.
 * It only queues the event; the upload worker sends it when there is a network.
 */
public class GeofenceBroadcastReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        GeofencingEvent event = GeofencingEvent.fromIntent(intent);
        if (event == null) return;
        if (event.hasError()) {
            // Typically GEOFENCE_NOT_AVAILABLE after location was switched
            // off: the registrations are gone and must be made again.
            GeofenceStore.failed(context, "geofence_error_" + event.getErrorCode());
            GeofenceUploadWorker.enqueue(context, true);
            return;
        }
        int transition = event.getGeofenceTransition();
        String kind = transition == Geofence.GEOFENCE_TRANSITION_ENTER ? "enter" : transition == Geofence.GEOFENCE_TRANSITION_EXIT ? "exit" : null;
        if (kind == null || event.getTriggeringGeofences() == null || !GeofenceStore.enrolled(context)) return;
        for (Geofence geofence : event.getTriggeringGeofences()) {
            try {
                GeofenceStore.enqueue(context, GeofenceRegistrar.event(kind, geofence.getRequestId(), event.getTriggeringLocation(), false));
            } catch (JSONException ignored) {
                // A malformed event is dropped; the periodic snapshot reconciles.
            }
        }
        GeofenceUploadWorker.enqueue(context, false);
    }
}
