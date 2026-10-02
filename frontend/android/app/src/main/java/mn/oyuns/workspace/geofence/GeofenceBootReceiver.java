package mn.oyuns.workspace.geofence;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Geofences do not survive a reboot or an app update: register them again. */
public class GeofenceBootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        String action = intent == null ? null : intent.getAction();
        if (!Intent.ACTION_BOOT_COMPLETED.equals(action) && !Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)) return;
        if (!GeofenceStore.enrolled(context)) return;
        GeofenceUploadWorker.schedulePeriodic(context);
        GeofenceUploadWorker.enqueue(context, true);
    }
}
