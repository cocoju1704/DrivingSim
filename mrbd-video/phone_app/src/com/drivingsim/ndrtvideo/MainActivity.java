package com.drivingsim.ndrtvideo;

import android.app.Activity;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.VideoView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * NDRT video on the phone (the phone condition of _Experiment2), driven by the experiment like the
 * glasses app (mrbd-video/public/app.js): it listens to the mrbd-video server's event stream
 * (/api/events) and does what the experiment PC sends (video_link.py, POST /api/control):
 *
 *   play {file, t, restart}  open the video (this phone's copy, else streamed from the server), seek
 *                   to t (t 0: where it was last left; with restart: from the start), play
 *   freeze          SAGAT: paused and covered (black), touches do nothing
 *   resume          uncovered, playing again if it was playing before
 *   alert {text}    paused, covered, a red line of text; alert_off: the text away (still covered)
 *   pause / seek    block end / jump
 *
 * Commands that carry a "device" other than "phone" (another condition's block) are ignored.
 * After each command and every 2 s it reports (POST /api/state, device "phone"): position, paused, covered.
 */
public class MainActivity extends Activity {
    static final int VERSION = 2;   // 2: play {restart}: the clip from its start
    static final String DEFAULT_SERVER = "https://video.cocoju.dev";
    static final String UA = "drivingsim-phone-video/1";   // Cloudflare refuses some default agents
    static final List<String> VIDEO_EXT = Arrays.asList(".mp4", ".m4v", ".webm", ".mov", ".mkv");

    final Handler ui = new Handler(Looper.getMainLooper());
    final ExecutorService reports = Executors.newSingleThreadExecutor();
    final ExecutorService work = Executors.newSingleThreadExecutor();   // lists, downloads
    SharedPreferences prefs;
    volatile String server;
    volatile boolean alive = true;
    volatile HttpURLConnection events;
    volatile boolean connected;
    volatile String netError = "";

    // views
    FrameLayout player;
    VideoView video;
    LinearLayout cover, osd;
    TextView coverText, osdTitle, osdTime, status, lastCommand;
    Button osdPlay;
    ScrollView homeScroll;
    LinearLayout list;
    EditText serverEdit;

    // player state
    boolean inPlayer, prepared, wantPlay;
    String title = "";
    static class Held { boolean wasPlaying, frozen; }
    Held held;   // during freeze / pause from the experiment
    final List<JSONObject> serverVideos = new ArrayList<>();
    final Map<String, String> progress = new HashMap<>();   // download progress by name

    // ------------------------------------------------------------------------------------------

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        prefs = getSharedPreferences("ndrt", MODE_PRIVATE);
        server = clean(prefs.getString("server", DEFAULT_SERVER));
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        buildViews();
        showHome();
        Thread t = new Thread(this::eventLoop, "events");
        t.setDaemon(true);
        t.start();
        ui.postDelayed(tick, 2000);
        ui.postDelayed(savePosition, 3000);
        refreshServerList();
    }

    @Override
    protected void onDestroy() {
        alive = false;
        HttpURLConnection c = events;
        if (c != null) work.execute(c::disconnect);
        super.onDestroy();
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (inPlayer) savePos();
    }

    @Override
    public void onWindowFocusChanged(boolean focus) {
        super.onWindowFocusChanged(focus);
        if (focus) immersive();
    }

    void immersive() {
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                | View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
    }

    @Override
    public void onBackPressed() {
        if (held != null && held.frozen) return;           // no way out during a question
        if (inPlayer) { goHome(); return; }
        super.onBackPressed();
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent e) {
        // volume keys work always; everything else is blocked while covered
        int k = e.getKeyCode();
        if (held != null && held.frozen && k != KeyEvent.KEYCODE_VOLUME_UP && k != KeyEvent.KEYCODE_VOLUME_DOWN) return true;
        return super.dispatchKeyEvent(e);
    }

    // ---------------------------------- views ---------------------------------------------------

    int dp(float v) { return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, getResources().getDisplayMetrics()); }

    TextView text(String s, float sp, int color) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(sp);
        t.setTextColor(color);
        return t;
    }

    Button button(String s, View.OnClickListener l) {
        Button b = new Button(this);
        b.setText(s);
        b.setAllCaps(false);
        b.setTextSize(16);
        b.setOnClickListener(l);
        return b;
    }

    void buildViews() {
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);

        // player: video, the controls (tap), the cover (SAGAT / TOR)
        player = new FrameLayout(this);
        video = new VideoView(this);
        player.addView(video, new FrameLayout.LayoutParams(-1, -1, Gravity.CENTER));
        View tap = new View(this);
        tap.setOnClickListener(v -> toggleOsd());
        player.addView(tap, new FrameLayout.LayoutParams(-1, -1));

        osd = new LinearLayout(this);
        osd.setOrientation(LinearLayout.VERTICAL);
        osd.setBackgroundColor(0xB0000000);
        osd.setPadding(dp(16), dp(8), dp(16), dp(8));
        LinearLayout titleRow = new LinearLayout(this);
        osdTitle = text("", 16, Color.WHITE);
        osdTime = text("", 16, 0xFFCCCCCC);
        titleRow.addView(osdTitle, new LinearLayout.LayoutParams(0, -2, 1));
        titleRow.addView(osdTime);
        osd.addView(titleRow);
        LinearLayout buttons = new LinearLayout(this);
        buttons.setGravity(Gravity.CENTER);
        buttons.addView(button("⏪ 10초", v -> { seekBy(-10000); showOsd(); }));
        osdPlay = button("❚❚", v -> { if (isPlaying()) pauseVideo(); else playVideo(); showOsd(); });
        buttons.addView(osdPlay, new LinearLayout.LayoutParams(dp(120), -2));
        buttons.addView(button("10초 ⏩", v -> { seekBy(10000); showOsd(); }));
        buttons.addView(button("목록", v -> goHome()));
        osd.addView(buttons);
        osd.setVisibility(View.GONE);
        player.addView(osd, new FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM));

        cover = new LinearLayout(this);
        cover.setBackgroundColor(Color.BLACK);
        cover.setGravity(Gravity.CENTER);
        cover.setClickable(true);   // swallows the touches
        coverText = text("", 34, 0xFFFF3B30);
        coverText.setTypeface(Typeface.DEFAULT_BOLD);
        coverText.setGravity(Gravity.CENTER);
        cover.addView(coverText);
        cover.setVisibility(View.GONE);
        player.addView(cover, new FrameLayout.LayoutParams(-1, -1));
        root.addView(player, new FrameLayout.LayoutParams(-1, -1));

        video.setOnPreparedListener(mp -> { prepared = true; if (!wantPlay) video.pause(); paintOsd(); });
        video.setOnCompletionListener(mp -> {
            prefs.edit().putInt("pos:" + title, 0).apply();
            wantPlay = false;
            showOsd();
            report("ended", "");
        });
        video.setOnErrorListener((mp, what, extra) -> {
            osdTitle.setText("⚠ 재생할 수 없습니다: " + title + " (" + what + "/" + extra + ")");
            osd.setVisibility(View.VISIBLE);
            report("play_failed", "");
            return true;
        });

        // home: server, status, the videos
        homeScroll = new ScrollView(this);
        homeScroll.setBackgroundColor(0xFF111418);
        LinearLayout home = new LinearLayout(this);
        home.setOrientation(LinearLayout.VERTICAL);
        home.setPadding(dp(24), dp(16), dp(24), dp(24));
        TextView head = text("NDRT 영상 · 휴대폰  v" + VERSION, 24, Color.WHITE);
        head.setTypeface(Typeface.DEFAULT_BOLD);
        home.addView(head);
        status = text("", 15, 0xFFAAAAAA);
        status.setPadding(0, dp(6), 0, dp(6));
        home.addView(status);
        LinearLayout serverRow = new LinearLayout(this);
        serverRow.setGravity(Gravity.CENTER_VERTICAL);
        serverRow.addView(text("서버 ", 15, 0xFFCCCCCC));
        serverEdit = new EditText(this);
        serverEdit.setText(server);
        serverEdit.setTextColor(Color.WHITE);
        serverEdit.setBackgroundColor(0xFF2C2C2E);
        serverEdit.setPadding(dp(12), dp(8), dp(12), dp(8));
        serverEdit.setSingleLine(true);
        serverEdit.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        // landscape: no full-screen keyboard editor over the buttons; Done saves
        serverEdit.setImeOptions(EditorInfo.IME_FLAG_NO_EXTRACT_UI | EditorInfo.IME_FLAG_NO_FULLSCREEN | EditorInfo.IME_ACTION_DONE);
        serverEdit.setOnEditorActionListener((v, id, e) -> { setServer(serverEdit.getText().toString()); return true; });
        serverRow.addView(serverEdit, new LinearLayout.LayoutParams(0, -2, 1));
        serverRow.addView(button("저장", v -> setServer(serverEdit.getText().toString())));
        serverRow.addView(button("새로고침", v -> { refreshServerList(); renderList(); }));
        home.addView(serverRow);
        lastCommand = text("실험 명령: 아직 없음", 15, 0xFFAAAAAA);
        lastCommand.setPadding(0, dp(4), 0, dp(10));
        home.addView(lastCommand);
        home.addView(text("실험 블록이 시작되면 ✓ 선택한 영상이 자동으로 열립니다 (시작 창에서 영상 파일을 정했으면 그 영상).\n"
                + "이 화면을 켜 둔 채로 두세요. 영상 화면을 누르면 조작 버튼이 나옵니다.", 14, 0xFF888888));
        list = new LinearLayout(this);
        list.setOrientation(LinearLayout.VERTICAL);
        list.setPadding(0, dp(8), 0, 0);
        home.addView(list);
        homeScroll.addView(home);
        root.addView(homeScroll, new FrameLayout.LayoutParams(-1, -1));
        setContentView(root);
    }

    // ---------------------------------- home ----------------------------------------------------

    File dir() {
        File d = getExternalFilesDir(Environment.DIRECTORY_MOVIES);
        if (d == null) d = new File(getFilesDir(), "Movies");
        d.mkdirs();
        return d;
    }

    static boolean isVideo(String name) {
        String n = name.toLowerCase(Locale.ROOT);
        for (String e : VIDEO_EXT) if (n.endsWith(e)) return true;
        return false;
    }

    List<File> localFiles() {
        List<File> out = new ArrayList<>();
        File[] all = dir().listFiles();
        if (all != null) for (File f : all) if (f.isFile() && isVideo(f.getName())) out.add(f);
        out.sort((a, b) -> a.getName().compareTo(b.getName()));
        return out;
    }

    String selected() {
        String s = prefs.getString("selected", "");
        List<File> local = localFiles();
        for (File f : local) if (f.getName().equals(s)) return s;
        return local.isEmpty() ? "" : local.get(0).getName();
    }

    static String clock(long ms) {
        long s = Math.max(0, ms / 1000);
        return s >= 3600 ? String.format(Locale.ROOT, "%d:%02d:%02d", s / 3600, s / 60 % 60, s % 60)
                         : String.format(Locale.ROOT, "%d:%02d", s / 60, s % 60);
    }

    static String size(long bytes) {
        return bytes >= 1L << 30 ? String.format(Locale.ROOT, "%.2f GB", bytes / (double) (1L << 30))
                                 : String.format(Locale.ROOT, "%.0f MB", bytes / (double) (1L << 20));
    }

    void showHome() {
        inPlayer = false;
        player.setVisibility(View.GONE);
        homeScroll.setVisibility(View.VISIBLE);
        renderList();
        paintStatus();
    }

    void goHome() {
        savePos();
        wantPlay = false;
        video.stopPlayback();
        prepared = false;
        held = null;
        cover.setVisibility(View.GONE);
        showHome();
        report("home", "");
    }

    void paintStatus() {
        String c = connected ? "● 서버 연결됨" : "○ 서버 연결 안 됨" + (netError.isEmpty() ? "" : " (" + netError + ")");
        status.setText(c + "   ·   저장 폴더: " + dir().getAbsolutePath());
        status.setTextColor(connected ? 0xFF4CD964 : 0xFFFF9500);
    }

    void renderList() {
        list.removeAllViews();
        String sel = selected();
        List<File> local = localFiles();
        list.addView(section("휴대폰에 저장된 영상 (" + local.size() + ")"));
        if (local.isEmpty()) list.addView(text("없음: 아래에서 받거나 PC에서 python build.py --videos-only 로 넣으세요", 15, 0xFF888888));
        List<String> names = new ArrayList<>();
        for (File f : local) {
            final String n = f.getName();
            names.add(n);
            int pos = prefs.getInt("pos:" + n, 0);
            LinearLayout row = row();
            TextView label = text((n.equals(sel) ? "✓ " : "   ") + n + "   " + size(f.length())
                    + (pos > 0 ? "   이어보기 " + clock(pos) : ""), 17, n.equals(sel) ? 0xFF4CD964 : Color.WHITE);
            row.addView(label, new LinearLayout.LayoutParams(0, -2, 1));
            row.addView(button("선택", v -> { prefs.edit().putString("selected", n).apply(); renderList(); }));
            row.addView(button("재생", v -> { prefs.edit().putString("selected", n).apply(); open(n, 0); }));
            row.addView(button("처음부터", v -> { prefs.edit().putInt("pos:" + n, 0).apply(); renderList(); }));
            list.addView(row);
        }
        List<JSONObject> remote = new ArrayList<>();
        synchronized (serverVideos) {
            for (JSONObject v : serverVideos) if (!names.contains(v.optString("name"))) remote.add(v);
        }
        list.addView(section("서버에만 있는 영상 (" + remote.size() + ")"));
        for (JSONObject v : remote) {
            final String n = v.optString("name");
            LinearLayout row = row();
            String p = progress.get(n);
            row.addView(text(n + "   " + size(v.optLong("size")) + (p != null ? "   " + p : ""), 17, Color.WHITE),
                    new LinearLayout.LayoutParams(0, -2, 1));
            if (p == null) row.addView(button("휴대폰에 받기", x -> download(n)));
            row.addView(button("스트리밍", x -> open(n, 0)));
            list.addView(row);
        }
    }

    TextView section(String s) {
        TextView t = text(s, 15, 0xFF8E8E93);
        t.setPadding(0, dp(14), 0, dp(4));
        return t;
    }

    LinearLayout row() {
        LinearLayout r = new LinearLayout(this);
        r.setGravity(Gravity.CENTER_VERTICAL);
        r.setPadding(0, dp(2), 0, dp(2));
        return r;
    }

    static String clean(String s) {
        s = s == null ? "" : s.trim();
        while (s.endsWith("/")) s = s.substring(0, s.length() - 1);
        if (s.isEmpty()) return DEFAULT_SERVER;
        if (!s.startsWith("http://") && !s.startsWith("https://")) s = "http://" + s;
        if (s.startsWith("http://") && s.substring(7).indexOf(':') < 0) s += ":8080";
        return s;
    }

    void setServer(String s) {
        server = clean(s);
        serverEdit.setText(server);
        prefs.edit().putString("server", server).apply();
        InputMethodManager imm = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
        if (imm != null) imm.hideSoftInputFromWindow(serverEdit.getWindowToken(), 0);
        HttpURLConnection c = events;
        if (c != null) work.execute(c::disconnect);   // the event loop reconnects to the new one
        synchronized (serverVideos) { serverVideos.clear(); }
        refreshServerList();
        immersive();
    }

    String mediaUrl(String name) {
        try {
            return server + "/media/" + URLEncoder.encode(name, "UTF-8").replace("+", "%20");
        } catch (Exception e) {
            return server + "/media/" + name;
        }
    }

    HttpURLConnection connect(String url, int readTimeout) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setConnectTimeout(8000);
        c.setReadTimeout(readTimeout);
        c.setRequestProperty("User-Agent", UA);
        return c;
    }

    void refreshServerList() {
        final String base = server;
        work.execute(() -> {
            try {
                HttpURLConnection c = connect(base + "/api/videos", 10000);
                String body = readAll(c.getInputStream());
                c.disconnect();
                JSONArray a = new JSONArray(body);
                List<JSONObject> got = new ArrayList<>();
                for (int i = 0; i < a.length(); i++) {
                    Object o = a.get(i);
                    if (o instanceof JSONObject) got.add((JSONObject) o);
                    else got.add(new JSONObject().put("name", String.valueOf(o)));
                }
                synchronized (serverVideos) { serverVideos.clear(); serverVideos.addAll(got); }
            } catch (Exception e) {
                netError = e.getClass().getSimpleName();
            }
            ui.post(() -> { if (!inPlayer) renderList(); });
        });
    }

    static String readAll(InputStream in) throws Exception {
        BufferedReader r = new BufferedReader(new InputStreamReader(in, "UTF-8"));
        StringBuilder sb = new StringBuilder();
        String line;
        while ((line = r.readLine()) != null) sb.append(line).append('\n');
        r.close();
        return sb.toString();
    }

    void download(final String name) {
        progress.put(name, "받는 중...");
        renderList();
        final String url = mediaUrl(name);
        work.execute(() -> {
            File part = new File(dir(), name + ".part");
            try {
                HttpURLConnection c = connect(url, 30000);
                long total = c.getContentLengthLong(), got = 0, shown = 0;
                try (InputStream in = c.getInputStream(); OutputStream out = new FileOutputStream(part)) {
                    byte[] buf = new byte[1 << 16];
                    int n;
                    while ((n = in.read(buf)) > 0) {
                        out.write(buf, 0, n);
                        got += n;
                        if (got - shown > (8L << 20)) {
                            shown = got;
                            final String p = total > 0 ? String.format(Locale.ROOT, "%d %%", got * 100 / total) : size(got);
                            ui.post(() -> { progress.put(name, p); if (!inPlayer) renderList(); });
                        }
                    }
                }
                c.disconnect();
                if (total > 0 && got != total) throw new Exception("끊김");
                if (!part.renameTo(new File(dir(), name))) throw new Exception("이름 바꾸기 실패");
                ui.post(() -> { progress.remove(name); if (!inPlayer) renderList(); });
            } catch (Exception e) {
                part.delete();
                final String m = "실패: " + e.getMessage();
                ui.post(() -> { progress.put(name, m); if (!inPlayer) renderList(); });
            }
        });
    }

    // ---------------------------------- player --------------------------------------------------

    /** Opens name (this phone's copy, else the server's), at t s (0: where it was left). */
    boolean open(String name, double t) {
        String n = name == null ? "" : name.trim();
        Uri uri = null;
        if (n.isEmpty()) n = selected();
        if (!n.isEmpty()) {
            File f = new File(dir(), n);
            if (f.isFile()) uri = Uri.fromFile(f);
        }
        if (uri == null) {
            if (n.isEmpty()) {
                synchronized (serverVideos) { if (!serverVideos.isEmpty()) n = serverVideos.get(0).optString("name"); }
            }
            if (n.isEmpty()) return false;
            uri = Uri.parse(mediaUrl(n));
        }
        title = n;
        held = null;
        cover.setVisibility(View.GONE);
        coverText.setText("");
        homeScroll.setVisibility(View.GONE);
        player.setVisibility(View.VISIBLE);
        inPlayer = true;
        prepared = false;
        wantPlay = true;
        osdTitle.setText(n);
        video.setVideoURI(uri);
        int at = t > 0 ? (int) (t * 1000) : prefs.getInt("pos:" + n, 0);
        if (at > 0) video.seekTo(at);
        video.start();
        immersive();
        showOsd();
        return true;
    }

    boolean isPlaying() { return inPlayer && (prepared ? video.isPlaying() : wantPlay); }

    void playVideo() { if (!inPlayer) return; wantPlay = true; video.start(); paintOsd(); }

    void pauseVideo() { if (!inPlayer) return; wantPlay = false; video.pause(); savePos(); paintOsd(); }

    void seekBy(int ms) {
        if (!inPlayer || !prepared) return;
        int d = video.getDuration();
        int to = Math.max(0, video.getCurrentPosition() + ms);
        if (d > 0) to = Math.min(to, d - 500);
        video.seekTo(to);
    }

    void savePos() {
        if (inPlayer && prepared && !title.isEmpty()) prefs.edit().putInt("pos:" + title, video.getCurrentPosition()).apply();
    }

    final Runnable hideOsd = () -> { if (isPlaying()) osd.setVisibility(View.GONE); };

    void showOsd() {
        paintOsd();
        osd.setVisibility(View.VISIBLE);
        ui.removeCallbacks(hideOsd);
        ui.postDelayed(hideOsd, 3500);
    }

    void toggleOsd() {
        if (osd.getVisibility() == View.VISIBLE && isPlaying()) osd.setVisibility(View.GONE);
        else showOsd();
    }

    void paintOsd() {
        osdPlay.setText(isPlaying() ? "❚❚" : "▶");
        if (prepared) osdTime.setText(clock(video.getCurrentPosition()) + " / " + clock(video.getDuration()));
    }

    final Runnable savePosition = new Runnable() {
        @Override public void run() {
            savePos();
            if (inPlayer && osd.getVisibility() == View.VISIBLE) paintOsd();
            ui.postDelayed(this, 1000);
        }
    };

    // ---------------------------------- the experiment ------------------------------------------

    final Runnable tick = new Runnable() {
        @Override public void run() {
            report("status", "");
            if (!inPlayer) paintStatus();
            ui.postDelayed(this, 2000);
        }
    };

    /** The experiment's command (UI thread). */
    void control(JSONObject d) {
        String a = d.optString("action");
        String id = d.optString("id");
        lastCommand.setText("실험 명령: " + a + (id.isEmpty() ? "" : " (" + id + ")") + "  "
                + new SimpleDateFormat("HH:mm:ss", Locale.ROOT).format(new Date()));
        switch (a) {
            case "freeze": case "pause": case "alert":
                if (held == null) { held = new Held(); held.wasPlaying = isPlaying(); }
                if (inPlayer) { wantPlay = false; video.pause(); savePos(); }
                if (!a.equals("pause")) {
                    held.frozen = true;
                    osd.setVisibility(View.GONE);
                    cover.setVisibility(View.VISIBLE);
                }
                if (a.equals("alert")) coverText.setText(d.optString("text", "지금 직접 운전하세요"));
                break;
            case "alert_off":
                coverText.setText("");
                break;
            case "resume": {
                Held h = held;
                held = null;
                cover.setVisibility(View.GONE);
                coverText.setText("");
                if (inPlayer && (h == null || h.wasPlaying)) playVideo();
                break;
            }
            case "play": {
                held = null;
                cover.setVisibility(View.GONE);
                coverText.setText("");
                String file = d.optString("file", "");
                double t = d.optDouble("t", 0);
                if (Double.isNaN(t)) t = 0;
                if (d.optBoolean("restart", false) && t <= 0) {
                    // the set's clip (video questions): from its start, not from where it was left
                    String n = file.isEmpty() ? (inPlayer ? title : selected()) : file;
                    prefs.edit().putInt("pos:" + n, 0).apply();
                    if (inPlayer && n.equals(title)) video.seekTo(0);
                }
                if (!inPlayer || (!file.isEmpty() && !file.equals(title))) {
                    boolean ok = open(file, t);
                    if (!ok) lastCommand.setText("⚠ 실험: 재생할 영상이 없습니다 (" + (file.isEmpty() ? "저장된 영상 없음" : file) + ")");
                    report(ok ? "play" : "play_failed", id);
                    return;
                }
                if (t > 0) video.seekTo((int) (t * 1000));
                playVideo();
                break;
            }
            case "seek":
                if (inPlayer) video.seekTo((int) (d.optDouble("t", 0) * 1000));
                break;
            default:   // calib: the glasses only
                return;
        }
        report(a, id);
    }

    /** State to the server (as the glasses app does), device "phone". */
    void report(String action, String id) {
        try {
            JSONObject b = new JSONObject();
            b.put("action", action).put("id", id == null ? "" : id).put("device", "phone")
             .put("screen", inPlayer ? "player" : "home").put("mode", inPlayer ? "file" : "")
             .put("title", inPlayer ? title : "")
             .put("t", inPlayer && prepared ? Math.round(video.getCurrentPosition()) / 1000.0 : JSONObject.NULL)
             .put("paused", inPlayer ? !isPlaying() : JSONObject.NULL)
             .put("frozen", held != null && held.frozen).put("ts", System.currentTimeMillis()).put("v", VERSION);
            final byte[] body = b.toString().getBytes("UTF-8");
            final String base = server;
            reports.execute(() -> {
                try {
                    HttpURLConnection c = connect(base + "/api/state", 6000);
                    c.setRequestMethod("POST");
                    c.setDoOutput(true);
                    c.setRequestProperty("Content-Type", "application/json");
                    c.setFixedLengthStreamingMode(body.length);
                    try (OutputStream o = c.getOutputStream()) { o.write(body); }
                    c.getResponseCode();
                    c.disconnect();
                } catch (Exception ignored) {
                }
            });
        } catch (Exception ignored) {
        }
    }

    /** The server's event stream, reconnected after a drop (background thread). */
    void eventLoop() {
        while (alive) {
            String base = server;
            try {
                HttpURLConnection c = connect(base + "/api/events", 45000);   // the server pings every 15 s
                c.setRequestProperty("Accept", "text/event-stream");
                c.setRequestProperty("Cache-Control", "no-cache");
                events = c;
                BufferedReader r = new BufferedReader(new InputStreamReader(c.getInputStream(), "UTF-8"));
                connected = true;
                netError = "";
                ui.post(() -> { if (!inPlayer) paintStatus(); });
                String line, event = "message";
                StringBuilder data = new StringBuilder();
                while (alive && base.equals(server) && (line = r.readLine()) != null) {
                    if (line.isEmpty()) {
                        if (data.length() > 0) dispatch(event, data.toString());
                        event = "message";
                        data.setLength(0);
                    } else if (line.startsWith("event:")) {
                        event = line.substring(6).trim();
                    } else if (line.startsWith("data:")) {
                        if (data.length() > 0) data.append('\n');
                        data.append(line.substring(5).trim());
                    }
                }
                c.disconnect();
            } catch (Exception e) {
                netError = e.getClass().getSimpleName();
            }
            events = null;
            connected = false;
            ui.post(() -> { if (!inPlayer) paintStatus(); });
            try { Thread.sleep(1500); } catch (InterruptedException ignored) { }
        }
    }

    void dispatch(String event, String data) {
        if (event.equals("library")) { refreshServerList(); return; }
        if (!event.equals("control")) return;
        try {
            final JSONObject d = new JSONObject(data);
            String device = d.optString("device", "");
            if (!device.isEmpty() && !device.equals("phone")) {   // another condition's block
                final String a = d.optString("action");
                ui.post(() -> lastCommand.setText("실험 명령: " + a + " (" + device + " 조건이라 무시)"));
                return;
            }
            ui.post(() -> control(d));
        } catch (Exception ignored) {
        }
    }

}
