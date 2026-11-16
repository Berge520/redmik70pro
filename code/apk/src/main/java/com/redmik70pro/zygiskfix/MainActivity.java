package com.redmik70pro.zygiskfix;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ContentValues;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.MediaStore;
import android.view.View;
import android.widget.Button;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;

/**
 * 极简一键修复界面。
 *
 * 设计取舍：
 * · 不用 Gradle/AndroidX，纯 framework API，单 Activity，APK 仅几十 KB。
 * · 脚本以 asset 形式内置，运行时释放到 app 私有目录，再用 `su -c sh` 执行，
 *   这样脚本可以随 APK 一起更新，也无需用户手动拷贝文件。
 * · 用 su 直接 su -c 单条命令，不依赖 libsu / 第三方库。
 * · 脚本末尾输出 `RESULT:<级别>:<原因>`，App 据此给出显眼结论，而不是让用户
 *   自己从一屏日志里找答案（真机测试里用户最常问的就是「到底成了没」）。
 */
public class MainActivity extends Activity {

    /**
     * 脚本未给出 RESULT 时的兜底等待上限。
     * fix 路径最坏耗时（[3] 8s ctl.restart + 50s svc 等待、system_server 60s、
     * [4] 40s + 15s、[5] 20s）约 200 秒，留出余量取 300 秒。
     */
    private static final long EXEC_TIMEOUT_MS = 300_000L;

    private TextView tvLog;
    private TextView tvResult;
    private TextView tvRunning;
    private TextView tvVersion;
    private TextView tvSafety;
    private ScrollView scroll;
    private Button btnFix;
    private Button btnCheck;
    private Button btnSave;

    private final Handler ui = new Handler(Looper.getMainLooper());
    private volatile boolean running = false;

    /** 上一次执行的结果暂存在私有目录，Activity 重建后据此恢复横幅。 */
    private static final String RESULT_FILE = "last_result.txt";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        tvLog = findViewById(R.id.tvLog);
        tvResult = findViewById(R.id.tvResult);
        tvRunning = findViewById(R.id.tvRunning);
        tvVersion = findViewById(R.id.tvVersion);
        tvSafety = findViewById(R.id.tvSafety);
        scroll = findViewById(R.id.scroll);
        btnFix = findViewById(R.id.btnFix);
        btnCheck = findViewById(R.id.btnCheck);
        btnSave = findViewById(R.id.btnSave);

        // 用匿名内部类而非 lambda：android.jar 不含 LambdaMetafactory，
        // 手工用 javac 编译 lambda 会报错，而 d8 去糖只在字节码层面生效。
        btnFix.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                confirmFix();
            }
        });
        btnCheck.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                run("check");
            }
        });
        btnSave.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                saveLog();
            }
        });
        // 内存/负载是会变的，横幅只反映「打开那一刻」；点一下强制重读，
        // 免得用户清理完后台还看着旧的红色警告。
        tvSafety.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                refreshSafetyBanner();
                Toast.makeText(MainActivity.this, "已重新读取当前状态", Toast.LENGTH_SHORT).show();
            }
        });

        append("准备就绪。\n"
                + "「一键激活」= 启动 Zygisk → 重建 zygote → 验证 Vector/LSPosed\n"
                + "「仅检测」= 只看当前状态，不做任何修改\n"
                + "「存日志」= 把当前日志存到「下载/ZygiskFix」以便反馈\n"
                + "注意：本机是临时 root，重启手机会导致 root 失效并需重新越狱，\n"
                + "      所以失败时请先用「仅检测」确认，不要急着重启。\n\n");
        String ver = readVersion();
        tvVersion.setText(ver);
        tvLog.append("版本：" + ver + "\n\n");
        bindRepoLink();
        refreshSafetyBanner();

        // 从后台被系统回收后重建：把上次的结论横幅恢复出来，避免用户以为没执行过。
        // 必须容忍坏文件：一键激活过程会重建 zygote，若恰在此刻被中断，文件可能只写了
        // 一半（标题在、颜色缺），此时 parseColor 会抛 IllegalArgumentException 让 App
        // 一打开就崩——而那一刻正是最需要打开 App 排查的时候。
        String last = readResultFile();
        if (last != null) {
            String[] parts = last.split("\n", 2);
            if (parts.length > 1 && !parts[0].trim().isEmpty()) {
                try {
                    showResult(parts[0], Color.parseColor(parts[1].trim()));
                } catch (IllegalArgumentException ignored) {
                    deleteQuietly(resultFile());
                }
            }
        }
    }

    /**
     * 刷新「现在能不能装 APK」的提示条。
     *
     * 背景：本机激活态下安装 APK 有把 swap 打穿、整机重启、临时 root 丢失的风险
     * （历史快照 SwapFree=64KB、MemFree=16MB）。注意 dex2oat 不是主因——本机
     * pm.dexopt.install 就是 speed-profile，小包几乎不编译；真正的压力来自包扫描、
     * PM 数据库写入，以及 zygote 被 ptrace 附着时所有模块进程的重建。
     * App 拦不住系统安装器，只能在高风险时把话说在最显眼的位置。
     *
     * 判据只用未授权 App 也能稳定读到的两个量：
     *   · SwapFree < 1GB —— 死机的直接前兆（历史死亡时仅剩 64KB）
     *   · MemAvailable < 600MB —— 与 fix.sh 入口闸门同一阈值
     * 任一命中就红色警告；全部健康则提示可以安装（通常是刚越狱、未注入的窗口）。
     * load 不作为判据：Android 16 的 SELinux 对未授权 App 域一律拒绝 /proc/loadavg。
     */
    private void refreshSafetyBanner() {
        long memAvail = readMeminfoKb("MemAvailable");
        long swapFree = readMeminfoKb("SwapFree");
        float load1 = readLoad1();
        // 读不到（极少数 ROM 隐藏 /proc）时不误报，直接不显示
        if (memAvail <= 0 && swapFree <= 0 && load1 < 0) {
            tvSafety.setVisibility(View.GONE);
            return;
        }

        boolean lowSwap = swapFree >= 0 && swapFree < 1024 * 1024;
        boolean lowMem = memAvail >= 0 && memAvail < 600 * 1024;

        // load 只是辅助参考：Android 16 的 SELinux 把 /proc/loadavg 标为 proc_loadavg，
        // 未授权 App 域一律 EACCES（与 uid 无关，su 切换 uid 能读是因为仍在 ksu 域）。
        // 所以读不到就不显示，不作为判据，避免整条横幅被一个拿不到的指标拖累。
        String stats = "MemAvailable " + mb(memAvail) + " · SwapFree " + mb(swapFree);
        if (load1 >= 0) {
            stats += " · load " + String.format(Locale.US, "%.2f", load1);
        }

        if (lowSwap || lowMem) {
            tvSafety.setText("⚠ 现在不建议安装/更新 APK：可能卡死并重启手机（重启会丢临时 root）。\n"
                    + stats + "\n先清理后台、等手机凉下来再操作。点本条可重新读取。");
            tvSafety.setTextColor(Color.parseColor("#C62828"));
            tvSafety.setBackgroundColor(Color.parseColor("#1FC62828"));
        } else {
            tvSafety.setText("✓ 资源充足，可以安全安装 APK。\n" + stats + "\n点本条可重新读取。");
            tvSafety.setTextColor(Color.parseColor("#1B7F3B"));
            tvSafety.setBackgroundColor(Color.parseColor("#1F1B7F3B"));
        }
        tvSafety.setVisibility(View.VISIBLE);
    }

    /** 从 /proc/meminfo 取某字段的 kB 值；取不到返回 -1。 */
    private static long readMeminfoKb(String key) {
        try (BufferedReader br = new BufferedReader(new java.io.FileReader("/proc/meminfo"))) {
            String line;
            while ((line = br.readLine()) != null) {
                if (line.startsWith(key + ":")) {
                    // 形如 "MemAvailable:   3541616 kB"
                    String[] p = line.substring(key.length() + 1).trim().split("\\s+");
                    return Long.parseLong(p[0]);
                }
            }
        } catch (Exception ignored) {
            // 读失败按“未知”处理，由调用方决定不显示
        }
        return -1;
    }

    /**
     * 取 1 分钟平均负载；取不到返回 -1。
     *
     * 实测：Android 16 上本机 App 域读 /proc/loadavg 会 EACCES（SELinux proc_loadavg），
     * 所以正常情况下一定返回 -1，调用方需容忍这一点，不能拿它当唯一判据。
     */
    private static float readLoad1() {
        try (BufferedReader br = new BufferedReader(new java.io.FileReader("/proc/loadavg"))) {
            String line = br.readLine();
            if (line != null) {
                return Float.parseFloat(line.trim().split("\\s+")[0]);
            }
        } catch (Exception ignored) {
            // 无权限或格式异常都按“未知”处理
        }
        return -1;
    }

    private static String mb(long kb) {
        if (kb < 0) {
            return "?";
        }
        return String.format(Locale.US, "%.2f GB", kb / 1024.0 / 1024.0);
    }

    /**
     * 把项目仓库地址显示在界面上，点击跳浏览器。
     *
     * 本 App 只有这一个 Activity，没有网页可挂，用户反馈问题时又常需要源码
     * 和文档上下文，所以直接把地址摆在首屏、可选中可点击，省得四处找。
     */
    private void bindRepoLink() {
        final String url = getString(R.string.repo_url);
        TextView tvRepo = findViewById(R.id.tvRepo);
        tvRepo.setText(getString(R.string.repo_label, url));
        tvRepo.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
                } catch (Exception e) {
                    // 极简 ROM 可能没有浏览器；此时至少让用户能复制地址
                    Toast.makeText(MainActivity.this, R.string.repo_open_failed, Toast.LENGTH_SHORT).show();
                }
            }
        });
    }

    /**
     * 「一键激活」前的二次确认。
     *
     * 会重建 zygote、屏幕黑一下、桌面重启；一旦误触，轻则白等一分多钟，
     * 重则在中途被打断，是最不该「点错就走」的动作。所以先弹窗说清代价，
     * 用户明确点「继续激活」才真正执行。
     */
    private void confirmFix() {
        if (running) {
            return;
        }
        new AlertDialog.Builder(this)
                .setTitle("确认一键激活？")
                .setMessage("会重建 zygote：屏幕可能全黑、桌面重启，约 10~30 秒，属正常。\n\n"
                        + "本机是临时 root，重启手机需重新越狱——过程中请勿手动重启。")
                .setNegativeButton("取消", null)
                .setPositiveButton("继续激活", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface dialog, int which) {
                        run("fix");
                    }
                })
                .show();
    }

    private void run(String mode) {
        if (running) {
            return;
        }
        running = true;
        btnFix.setEnabled(false);
        btnCheck.setEnabled(false);
        btnSave.setEnabled(false);
        tvLog.setText("");
        tvRunning.setVisibility(View.VISIBLE);
        showResult(mode.equals("fix") ? "正在执行一键激活…" : "正在检测…", Color.parseColor("#666666"));
        append(mode.equals("fix") ? "===== 开始一键激活 =====\n\n" : "===== 开始检测 =====\n\n");
        deleteQuietly(new File(getFilesDir(), RESULT_FILE));

        new Thread(new Runnable() {
            @Override
            public void run() {
                final Result r = exec(mode);
                ui.post(new Runnable() {
                    @Override
                    public void run() {
                        // 重建 zygote 期间系统会重建 Activity：此时旧的已销毁，
                        // 再更新它的控件没有意义（新实例会从 last_result.txt 恢复结论）。
                        if (isFinishing() || isDestroyed()) {
                            // 关键：结论必须无条件落盘。之前这里直接 return，
                            // 导致激活成功后新实例读到的还是更早的旧结论（甚至为空），
                            // 用户点完「一键激活」看到的是一屏空白，误以为没生效。
                            writeResultFile(r);
                            // 已销毁时不会再有 Activity 来显示这个结论，重新拉一次自己，
                            // 让新实例在 onCreate 里从 last_result.txt 恢复横幅。
                            relaunchSelf();
                            return;
                        }
                        finishRun(r);
                    }
                });
            }
        }, "zygisk-fix").start();
    }

    /**
     * 把自己重新拉到前台，用于「执行期间 Activity 被重建」的场景。
     *
     * 一键激活会重建 zygote，system_server 随之重启，本 App 的 Activity 必然被销毁。
     * 结论已经写进 last_result.txt，但没有任何存活的界面能显示它，所以这里再拉一次，
     * 新实例在 onCreate 里读文件恢复横幅。
     *
     * 加 NEW_TASK | CLEAR_TOP：本类不是 singleTop，若实例还残留会导致叠一层新界面，
     * CLEAR_TOP 能让它复用已存在实例。
     */
    private void relaunchSelf() {
        try {
            Intent i = new Intent(this, MainActivity.class);
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
            startActivity(i);
        } catch (Exception ignored) {
            // 拉不起来也不影响结论已落盘，用户手动打开 App 一样能看到
        }
    }

    /**
     * 读取本应用版本号，供标题栏与日志显示。
     *
     * 刻意不在这里写死常量：从 PackageManager 读，才能保证界面显示的
     * 一定是「这个 APK 实际被系统记录的版本」。若另写一份常量，
     * 发版时忘记同步就会出现「界面显示 1.2.0、系统里却是 1.1.0」，
     * 排查时反而误导。versionName / versionCode 统一在 AndroidManifest 维护。
     *
     * 同时带上 versionCode：用户反馈问题时能一眼确认装的是哪一版，
     * 覆盖安装过旧包时也好对照。
     */
    private String readVersion() {
        try {
            PackageInfo pi = getPackageManager().getPackageInfo(getPackageName(), 0);
            String name = pi.versionName == null ? "未知" : pi.versionName;
            return "v" + name + " (" + pi.versionCode + ")";
        } catch (Exception e) {
            // 极少数 ROM 的 PackageManager 会抛异常，不能因此让界面起不来
            return "v? (" + e.getClass().getSimpleName() + ")";
        }
    }

    /** 统一收尾：恢复按钮、隐藏进度、显示横幅、落盘结果。 */
    private void finishRun(Result r) {
        running = false;
        btnFix.setEnabled(true);
        btnCheck.setEnabled(true);
        btnSave.setEnabled(tvLog.length() > 0);
        tvRunning.setVisibility(View.GONE);
        // 修复前后内存会明显变化（zygote 重建），横幅跟着更新才有参考价值
        refreshSafetyBanner();
        showResult(r.title, r.color);
        if (r.detail != null) {
            append("\n" + r.detail + "\n");
        }
        writeResultFile(r);
    }

    private File resultFile() {
        return new File(getFilesDir(), RESULT_FILE);
    }

    private void writeResultFile(Result r) {
        try (OutputStream os = new FileOutputStream(resultFile())) {
            os.write((r.title + "\n" + String.format("#%08X", r.color)).getBytes(StandardCharsets.UTF_8));
        } catch (Exception ignored) {
            // 只是恢复用，写失败不影响主流程
        }
    }

    private String readResultFile() {
        try {
            File f = resultFile();
            if (!f.exists()) {
                return null;
            }
            return readAll(f).trim();
        } catch (Exception e) {
            return null;
        }
    }

    private static String readAll(File f) throws Exception {
        try (InputStream in = new java.io.FileInputStream(f)) {
            java.io.ByteArrayOutputStream bos = new java.io.ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) {
                bos.write(buf, 0, n);
            }
            return new String(bos.toByteArray(), StandardCharsets.UTF_8);
        }
    }

    /**
     * 把当前日志存到公共「下载/ZygiskFix」目录。
     *
     * 手工构建不引 AndroidX，没有运行时权限申请流程，所以用 MediaStore：
     * API 29+ 的 Downloads 集合登记自己的文件无需任何权限。
     * minSdk 是 26，MediaStore.Downloads 类在 26~28 上不存在（会 NoClassDefFoundError），
     * 那两版直接退化为文本分享，不碰该类。
     */
    private void saveLog() {
        String text = tvLog.getText().toString();
        if (text.isEmpty()) {
            Toast.makeText(this, "日志为空", Toast.LENGTH_SHORT).show();
            return;
        }
        String name = "zygiskfix-"
                + new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(new Date()) + ".log";
        if (android.os.Build.VERSION.SDK_INT < 29) {
            shareLog(text, name);
            return;
        }
        try {
            ContentValues cv = new ContentValues();
            cv.put(MediaStore.Downloads.DISPLAY_NAME, name);
            cv.put(MediaStore.Downloads.MIME_TYPE, "text/plain");
            cv.put(MediaStore.Downloads.RELATIVE_PATH,
                    Environment.DIRECTORY_DOWNLOADS + "/ZygiskFix");
            Uri uri = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, cv);
            if (uri == null) {
                throw new IllegalStateException("insert 返回 null");
            }
            try (OutputStream os = getContentResolver().openOutputStream(uri)) {
                os.write(text.getBytes(StandardCharsets.UTF_8));
            }
            Toast.makeText(this, "已保存到 下载/ZygiskFix/" + name, Toast.LENGTH_LONG).show();
        } catch (Exception e) {
            // 部分 ROM 的 Downloads 集合不可写，退回分享，至少能让用户把日志发出去
            Toast.makeText(this, "保存失败，改为分享：" + e.getMessage(), Toast.LENGTH_LONG).show();
            shareLog(text, name);
        }
    }

    private void shareLog(String text, String name) {
        try {
            // 私有目录的文件不能直接附给别的 App，走纯文本分享
            startActivity(Intent.createChooser(new Intent(Intent.ACTION_SEND)
                    .setType("text/plain")
                    .putExtra(Intent.EXTRA_SUBJECT, name)
                    .putExtra(Intent.EXTRA_TEXT, text), "分享日志"));
        } catch (Exception e) {
            Toast.makeText(this, "分享失败：" + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    private static void deleteQuietly(File f) {
        if (f.exists()) {
            //noinspection ResultOfMethodCallIgnored
            f.delete();
        }
    }

    /** 结果横幅的内容。 */
    private static final class Result {
        final String title;
        final int color;
        /** 追加到日志末尾的补充说明，可为 null。 */
        final String detail;

        Result(String title, int color, String detail) {
            this.title = title;
            this.color = color;
            this.detail = detail;
        }
    }

    private void showResult(String text, int color) {
        tvResult.setText(text);
        tvResult.setTextColor(color);
        tvResult.setVisibility(View.VISIBLE);
    }

    /** 把脚本的 `RESULT:级别:原因` 翻译成用户看得懂的一句话。 */
    private Result toResult(String level, String reason) {
        int ok = Color.parseColor("#1B7F3B");
        int warn = Color.parseColor("#B26A00");
        int bad = Color.parseColor("#C62828");

        if ("OK".equals(level)) {
            if ("ALREADY".equals(reason)) {
                return new Result("✓ 已处于激活状态，无需修复", ok, null);
            }
            return new Result("✓ 激活完成，请打开用到模块的 App 实测", ok, null);
        }
        if ("WARN".equals(level)) {
            // 这条路径千万别建议“重启手机”：临时 root 一重启就没了，要重新越狱。
            return new Result("⚠️ 部分成功：Zygisk 已注入，但链路未完全打通",
                    warn,
                    "建议：先等 30 秒再点「仅检测」，不要急着重启——重启会丢失临时 root。");
        }
        if (reason == null) {
            reason = "";
        }
        switch (reason) {
            case "NOROOT":
                return new Result("✗ 没有拿到 root", bad,
                        "请打开 KernelSU/APatch/Magisk 管理器，在「超级用户」里把本应用设为允许后重试。");
            case "NOADB":
                return new Result("✗ Root 环境异常", bad,
                        "读不到 /data/adb/modules。临时 root 可能已失效，请重新越狱后重试。");
            case "NOZYGISK":
                return new Result("✗ 没装 Zygisk 框架", bad,
                        "请先在 KernelSU 管理器里刷入 NeoZygisk 或 Zygisk Next 后再试。");
            case "NOINJECT":
                return new Result("✗ 未注入成功", bad,
                        "请按日志里的排查步骤逐条确认；最常见的原因是模块被停用或 zygote 未成功重建。");
            case "NOTACTIVE":
                return new Result("✗ 当前未注入", warn,
                        "点「一键激活」修复。");
            case "NOZYGOTE":
                return new Result("✗ zygote 未恢复", bad,
                        "请等 1 分钟看屏幕是否恢复：恢复了就点「仅检测」；"
                                + "界面一直不可用再手动重启并重新越狱。不要连续点按钮。");
            case "NOSS":
                return new Result("✗ 桌面服务未恢复", bad,
                        "zygote 已经重建，但 system_server 没起来。等 1 分钟看桌面是否恢复，"
                                + "再点「仅检测」；不要急着重启（会丢临时 root）。");
            case "BUSY":
                return new Result("⚠️ 手机负载过高，已中止", warn,
                        "为避免卡死/整机重启，这次没有做任何重启动作。"
                                + "请等手机凉下来、确认界面流畅后再点「一键激活」。");
            case "LOWMEM":
                return new Result("⚠️ 可用内存过低，已中止", warn,
                        "这次没有做任何重启动作。请先清理后台应用，"
                                + "等手机不烫、界面流畅后再点「一键激活」。");
            default:
                return new Result("✗ 修复未通过", bad, "原因标记：" + reason);
        }
    }

    /**
     * 外部脚本候选路径，按优先级尝试。
     *
     * 为什么不是只用一个路径：真机验证发现 /sdcard/Download 的所有者是 u0_a245、
     * 权限 2770，而本应用 uid 是 10295、没有存储权限，**读不进去**。
     * 写成单路径会让「外部脚本」功能表面存在、实际永远回落内置副本。
     *
     * /data/local/tmp 权限 1777，任何 uid 都能读，adb push 也直接可用，
     * 所以放在第一位。sdcard 路径保留在后面：万一以后给了存储权限仍可用。
     */
    private static final String[] EXTERNAL_SCRIPTS = {
            "/data/local/tmp/fix.sh",
            "/sdcard/Download/fix.sh",
            "/storage/emulated/0/Download/fix.sh",
    };

    /**
     * 取本次要执行的脚本：外部候选 > APK 内置 assets。
     *
     * 为什么要支持外部脚本：本机是临时 root，Zygisk 激活时安装 APK 会打穿
     * swap 导致整机重启、root 丢失。把脚本放外部，改逻辑只需 adb push 一个
     * 文本文件，完全不触发安装。全部候选都不可用时自动回落内置副本，
     * 不会因为用户没推文件就跑不起来。
     */
    private File releaseScript() {
        for (String path : EXTERNAL_SCRIPTS) {
            String reason = externalScriptReason(path);
            if (reason == null) {
                File f = new File(path);
                // 打上大小和修改时间：外部脚本可能比内置版本旧，出问题时需要一眼看出
                // 本次到底跑的是哪一份，否则会误以为“改的脚本没生效”或反之。
                append("[App] 使用外部脚本 " + path
                        + "（" + f.length() + "B, "
                        + new SimpleDateFormat("MM-dd HH:mm", Locale.US).format(new Date(f.lastModified()))
                        + "）\n");
                return f;
            }
            append("[App] 跳过 " + path + "（" + reason + "）\n");
        }
        append("[App] 外部脚本均不可用，回落内置脚本\n");

        File out = new File(getFilesDir(), "fix.sh");
        try (InputStream in = getAssets().open("fix.sh");
             OutputStream os = new FileOutputStream(out)) {
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) {
                os.write(buf, 0, n);
            }
        } catch (Exception e) {
            append("[App] 释放脚本失败: " + e + "\n");
            return null;
        }
        return out;
    }

    /** 该路径可用时返回 null，否则返回不可用原因（写进日志便于排查）。 */
    private String externalScriptReason(String path) {
        File f = new File(path);
        if (!f.exists()) {
            return "不存在";
        }
        // 注意顺序：先判长度再判可读，否则 canRead() 在某些 FUSE 目录上
        // 会因为权限被拒而直接 false，掩盖“文件根本没推完整”这个更常见的原因
        if (f.length() < 200) {
            return "过小(" + f.length() + "B)，疑似未推送完整";
        }
        if (!f.canRead()) {
            // adb push 出来常见 600 root，root 能读但 App 不行，给出可直接照抄的修法
            return "无读权限（需 chmod 644）";
        }
        return null;
    }

    /**
     * 按顺序尝试多种提权方式。
     *
     * 部分临时 Root 环境（如本机的 KernelSU late-load）里 /system/bin/su 对
     * untrusted_app 域不可执行，直接 new ProcessBuilder("su", ...) 会抛
     * IOException "Cannot run program su: error=13, Permission denied"。
     * 因此逐个尝试常见路径，把失败原因完整打印出来，便于定位是缺 root
     * 还是该环境的 su 不可用。
     */
    private String[][] suCandidates() {
        return new String[][]{
                {"su", "-c"},
                {"/system/bin/su", "-c"},
                {"/debug_ramdisk/su", "-c"},
                // KernelSU 在部分版本里把 su 入口放在这里，与 su 参数一致
                {"/data/adb/ksu/bin/ksu", "-c"},
        };
    }

    /** 执行脚本并流式把输出刷到界面，返回解析后的结果。 */
    private Result exec(String mode) {
        File script = releaseScript();
        if (script == null) {
            return new Result("✗ 内置脚本释放失败", Color.parseColor("#C62828"),
                    "重装本应用后再试。");
        }
        String cmd = "sh " + script.getAbsolutePath() + " " + mode;

        Process p = null;
        List<String> failed = new ArrayList<String>();
        for (String[] c : suCandidates()) {
            try {
                p = new ProcessBuilder(c[0], c[1], cmd)
                        .redirectErrorStream(true)
                        .start();
                append("[App] 使用 " + c[0] + "\n\n");
                break;
            } catch (Exception e) {
                failed.add(c[0] + ": " + e.getMessage());
                append("[App] " + c[0] + " 不可用: " + e.getMessage() + "\n");
            }
        }
        if (p == null) {
            return new Result("✗ 无法获得 root 权限", Color.parseColor("#C62828"),
                    "本应用没有被授予 root。请打开 KernelSU 管理器，"
                            + "在「超级用户」里找到「Zygisk 修复」，手动打开授权开关后重试"
                            + "（KernelSU 不会自动弹出授权窗口）。\n"
                            + "已尝试的入口：\n  " + join(failed, "\n  "));
        }

        final Process proc = p;
        final String[] marker = new String[2];
        Thread reader = new Thread(new Runnable() {
            @Override
            public void run() {
                try (BufferedReader r = new BufferedReader(
                        new InputStreamReader(proc.getInputStream(), StandardCharsets.UTF_8))) {
                    String line;
                    while ((line = r.readLine()) != null) {
                        if (line.startsWith("RESULT:")) {
                            String[] parts = line.split(":", 3);
                            marker[0] = parts.length > 1 ? parts[1] : "";
                            marker[1] = parts.length > 2 ? parts[2] : "";
                            continue;
                        }
                        final String l = line;
                        ui.post(new Runnable() {
                            @Override
                            public void run() {
                                append(l + "\n");
                            }
                        });
                    }
                } catch (Exception e) {
                    // 进程被杀时读取会抛异常，属于正常收尾路径，不再打扰用户
                }
            }
        }, "zygisk-fix-reader");
        reader.start();

        try {
            reader.join(EXEC_TIMEOUT_MS);
            if (reader.isAlive()) {
                // destroy() 只发 SIGTERM，su/zygote 相关进程常常忽略它，
                // 必须用 destroyForcibly 才能真正收掉，否则脚本会在后台继续
                // 执行（包括可能的重建 zygote 动作），与界面提示不一致。
                proc.destroyForcibly();
                return new Result("✗ 执行超时", Color.parseColor("#C62828"),
                        "超过 " + (EXEC_TIMEOUT_MS / 1000) + " 秒仍未结束，已终止。"
                                + "请稍等再点「仅检测」看看当前状态，不要连点按钮。");
            }
            // reader 结束意味着 stdout 已关闭，正常情况下进程也已退出；
            // 但仍用有界等待，避免极端情况下界面线程卡在这里。
            int exit = proc.waitFor(10, java.util.concurrent.TimeUnit.SECONDS) ? proc.exitValue() : -1;
            // 脚本本身总以 0 退出（结果靠 RESULT: 标记传递），故非 0 基本等于
            // su 被拒绝（KernelSU 拒绝授权时的退出码）。
            if (marker[0] == null) {
                if (exit != 0) {
                    return new Result("✗ root 授权被拒绝", Color.parseColor("#C62828"),
                            "su 退出码=" + exit + "。请打开 KernelSU 管理器，"
                                    + "在「超级用户」里手动允许「Zygisk 修复」使用 root 后重试。");
                }
                return new Result("✗ 脚本没有给出结论", Color.parseColor("#C62828"),
                        "请把上面的日志反馈给开发者。");
            }
            return toResult(marker[0], marker[1]);
        } catch (InterruptedException e) {
            proc.destroyForcibly();
            return new Result("✗ 已中断", Color.parseColor("#C62828"), null);
        }
    }

    private static String join(List<String> list, String sep) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < list.size(); i++) {
            if (i > 0) {
                sb.append(sep);
            }
            sb.append(list.get(i));
        }
        return sb.toString();
    }

    /**
     * 追加日志。调用方可能在后台线程（exec 里探测 su、reader 线程），
     * 而 TextView 只允许主线程改，所以统一转到主线程执行。
     * 曾出现过 `su 不可用: Only the original thread that created a view
     * hierarchy can touch its views`：真机上 "su" 这条其实可用，是被这个
     * 异常打断才误判为不可用、退到 /system/bin/su。
     */
    private void append(final String text) {
        ui.post(new Runnable() {
            @Override
            public void run() {
                tvLog.append(text);
                scroll.fullScroll(View.FOCUS_DOWN);
            }
        });
    }
}
