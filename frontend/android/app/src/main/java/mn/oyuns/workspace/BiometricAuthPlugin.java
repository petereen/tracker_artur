package mn.oyuns.workspace;

import androidx.annotation.NonNull;
import androidx.biometric.BiometricManager;
import androidx.biometric.BiometricPrompt;
import androidx.core.content.ContextCompat;
import androidx.fragment.app.FragmentActivity;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/** Fingerprint / face prompt for the app lock and for confirming consent. */
@CapacitorPlugin(name = "BiometricAuth")
public class BiometricAuthPlugin extends Plugin {
    private static final int BIOMETRIC = BiometricManager.Authenticators.BIOMETRIC_WEAK;
    private static final int WITH_DEVICE_CREDENTIAL = BIOMETRIC | BiometricManager.Authenticators.DEVICE_CREDENTIAL;

    @PluginMethod
    public void isAvailable(PluginCall call) {
        BiometricManager manager = BiometricManager.from(getContext());
        boolean biometric = manager.canAuthenticate(BIOMETRIC) == BiometricManager.BIOMETRIC_SUCCESS;
        boolean secure = manager.canAuthenticate(WITH_DEVICE_CREDENTIAL) == BiometricManager.BIOMETRIC_SUCCESS;
        JSObject result = new JSObject();
        result.put("available", biometric);
        result.put("deviceSecure", secure);
        result.put("biometryType", biometric ? "biometric" : "none");
        call.resolve(result);
    }

    @PluginMethod
    public void authenticate(PluginCall call) {
        // With the screen-lock fallback a user whose finger or face is not
        // recognised is never locked out of the app.
        boolean allowDeviceCredential = Boolean.TRUE.equals(call.getBoolean("allowDeviceCredential", true));
        int authenticators = allowDeviceCredential ? WITH_DEVICE_CREDENTIAL : BIOMETRIC;
        if (BiometricManager.from(getContext()).canAuthenticate(authenticators) != BiometricManager.BIOMETRIC_SUCCESS) {
            call.reject("Biometric authentication is not available", "unavailable");
            return;
        }
        BiometricPrompt.PromptInfo.Builder info = new BiometricPrompt.PromptInfo.Builder()
            .setTitle(call.getString("title", "OYUNS"))
            .setSubtitle(call.getString("reason", ""))
            .setAllowedAuthenticators(authenticators);
        if (!allowDeviceCredential) info.setNegativeButtonText(call.getString("cancelLabel", "Cancel"));
        FragmentActivity activity = getActivity();
        activity.runOnUiThread(() -> new BiometricPrompt(activity, ContextCompat.getMainExecutor(activity), new BiometricPrompt.AuthenticationCallback() {
            @Override
            public void onAuthenticationSucceeded(@NonNull BiometricPrompt.AuthenticationResult result) {
                JSObject output = new JSObject();
                output.put("success", true);
                call.resolve(output);
            }

            @Override
            public void onAuthenticationError(int code, @NonNull CharSequence message) {
                boolean cancelled = code == BiometricPrompt.ERROR_USER_CANCELED || code == BiometricPrompt.ERROR_NEGATIVE_BUTTON || code == BiometricPrompt.ERROR_CANCELED;
                call.reject(message.toString(), cancelled ? "cancelled" : "failed");
            }
        }).authenticate(info.build()));
    }
}
