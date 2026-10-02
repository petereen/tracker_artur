package mn.oyuns.workspace;

import com.getcapacitor.BridgeActivity;
import android.os.Bundle;
import mn.oyuns.workspace.geofence.GeofencePlugin;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(AudioRoutePlugin.class);
        registerPlugin(NativeCapabilitiesPlugin.class);
        registerPlugin(GeofencePlugin.class);
        registerPlugin(BiometricAuthPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
