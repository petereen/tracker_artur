package mn.oyuns.workspace;

import android.content.Context;
import android.media.AudioManager;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.annotation.CapacitorPlugin;

@CapacitorPlugin(name = "AudioRoute")
public class AudioRoutePlugin extends Plugin {
    private AudioManager audioManager;

    @Override
    public void load() {
        audioManager = (AudioManager) getContext().getSystemService(Context.AUDIO_SERVICE);
    }

    @com.getcapacitor.PluginMethod
    public void setRoute(PluginCall call) {
        boolean speaker = "speaker".equals(call.getString("route", "default"));
        audioManager.setMode(AudioManager.MODE_IN_COMMUNICATION);
        audioManager.setSpeakerphoneOn(speaker);
        JSObject result = new JSObject();
        result.put("route", speaker ? "speaker" : "default");
        call.resolve(result);
    }
}
