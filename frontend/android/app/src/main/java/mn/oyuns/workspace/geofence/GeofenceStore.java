package mn.oyuns.workspace.geofence;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.HashSet;
import java.util.Set;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/**
 * State the geofence layer needs while the web layer is not running: the API
 * address, the sites, the queue of unsent events and the device credential.
 * The credential is encrypted with a key that never leaves the Android Keystore.
 */
public final class GeofenceStore {
    /** Build number of the native layer; see NativeCapabilitiesPlugin. */
    public static final int NATIVE_VERSION = 2;

    private static final String PREFS = "oyuns_geofence";
    private static final String KEY_ALIAS = "oyuns_geofence_credential";
    private static final String API_BASE_URL = "apiBaseUrl";
    private static final String CREDENTIAL = "credential";
    private static final String SITES = "sites";
    private static final String MODE = "mode";
    private static final String PENDING = "pending";
    private static final String LAST_UPLOAD = "lastUpload";
    private static final String LAST_ERROR = "lastError";
    private static final int MAX_PENDING = 200;
    private static final Object LOCK = new Object();

    private GeofenceStore() {}

    private static SharedPreferences prefs(Context context) {
        return context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    public static void configure(Context context, String apiBaseUrl, String credential) throws Exception {
        prefs(context).edit().putString(API_BASE_URL, apiBaseUrl).putString(CREDENTIAL, encrypt(credential)).remove(LAST_ERROR).apply();
    }

    public static String apiBaseUrl(Context context) {
        return prefs(context).getString(API_BASE_URL, null);
    }

    public static String credential(Context context) {
        String stored = prefs(context).getString(CREDENTIAL, null);
        if (stored == null) return null;
        try {
            return decrypt(stored);
        } catch (Exception error) {
            return null;
        }
    }

    public static boolean enrolled(Context context) {
        return prefs(context).contains(CREDENTIAL);
    }

    public static void clear(Context context) {
        synchronized (LOCK) {
            prefs(context).edit().clear().apply();
        }
    }

    public static void saveServerPayload(Context context, JSONObject payload) {
        JSONObject config = payload.optJSONObject("config");
        JSONArray sites = payload.optJSONArray("sites");
        prefs(context).edit()
            .putString(MODE, config == null ? "off" : config.optString("mode", "off"))
            .putString(SITES, sites == null ? "[]" : sites.toString())
            .apply();
    }

    public static String mode(Context context) {
        return prefs(context).getString(MODE, "off");
    }

    public static JSONArray sites(Context context) {
        try {
            return new JSONArray(prefs(context).getString(SITES, "[]"));
        } catch (JSONException error) {
            return new JSONArray();
        }
    }

    public static void enqueue(Context context, JSONObject event) {
        synchronized (LOCK) {
            JSONArray events = pending(context);
            events.put(event);
            while (events.length() > MAX_PENDING) events.remove(0);
            prefs(context).edit().putString(PENDING, events.toString()).commit();
        }
    }

    public static JSONArray pending(Context context) {
        try {
            return new JSONArray(prefs(context).getString(PENDING, "[]"));
        } catch (JSONException error) {
            return new JSONArray();
        }
    }

    public static void removeSent(Context context, JSONArray sent) {
        synchronized (LOCK) {
            Set<String> ids = new HashSet<>();
            for (int index = 0; index < sent.length(); index++) {
                JSONObject event = sent.optJSONObject(index);
                if (event != null) ids.add(event.optString("client_event_id"));
            }
            JSONArray remaining = new JSONArray();
            JSONArray events = pending(context);
            for (int index = 0; index < events.length(); index++) {
                JSONObject event = events.optJSONObject(index);
                if (event != null && !ids.contains(event.optString("client_event_id"))) remaining.put(event);
            }
            prefs(context).edit().putString(PENDING, remaining.toString()).commit();
        }
    }

    public static void uploaded(Context context, String timestamp) {
        prefs(context).edit().putString(LAST_UPLOAD, timestamp).remove(LAST_ERROR).apply();
    }

    public static void failed(Context context, String reason) {
        prefs(context).edit().putString(LAST_ERROR, reason).apply();
    }

    public static String lastUpload(Context context) {
        return prefs(context).getString(LAST_UPLOAD, null);
    }

    public static String lastError(Context context) {
        return prefs(context).getString(LAST_ERROR, null);
    }

    private static SecretKey key() throws Exception {
        KeyStore keyStore = KeyStore.getInstance("AndroidKeyStore");
        keyStore.load(null);
        if (keyStore.containsAlias(KEY_ALIAS)) {
            return ((KeyStore.SecretKeyEntry) keyStore.getEntry(KEY_ALIAS, null)).getSecretKey();
        }
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256)
            .build());
        return generator.generateKey();
    }

    private static String encrypt(String value) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key());
        byte[] iv = cipher.getIV();
        byte[] encrypted = cipher.doFinal(value.getBytes(StandardCharsets.UTF_8));
        ByteBuffer buffer = ByteBuffer.allocate(1 + iv.length + encrypted.length);
        buffer.put((byte) iv.length).put(iv).put(encrypted);
        return Base64.encodeToString(buffer.array(), Base64.NO_WRAP);
    }

    private static String decrypt(String stored) throws Exception {
        ByteBuffer buffer = ByteBuffer.wrap(Base64.decode(stored, Base64.NO_WRAP));
        byte[] iv = new byte[buffer.get()];
        buffer.get(iv);
        byte[] encrypted = new byte[buffer.remaining()];
        buffer.get(encrypted);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, iv));
        return new String(cipher.doFinal(encrypted), StandardCharsets.UTF_8);
    }
}
