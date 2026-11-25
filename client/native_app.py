"""Native Tk control surface; direct App calls, no browser or HTTP UI server."""

import io
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

R = Path(__file__).resolve().parent.parent
# Python's standard installer provides Tcl/Tk; do not hardcode a portable runtime.
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from launch_local import free, prepare
from PIL import Image, ImageTk

from ui import App, list_cameras


class Service:
    def __init__(self):
        self.app = None
        self.backend = None
        self.lock = threading.Lock()
        self.closed = False

    def boot(self):
        free(18990)
        free(18991)
        config = prepare(R, 18991)
        logs = R / "logs"
        logs.mkdir(exist_ok=True)
        self.log = (logs / "native-backend.log").open("a", encoding="utf8")
        with self.lock:
            if self.closed:
                raise RuntimeError("启动已取消")
            self.backend = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    str(R / "portable_entry.py"),
                    "server/backend.py",
                    "--config",
                    str(config),
                    "--port",
                    "18991",
                ],
                cwd=R,
                stdout=self.log,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                env=dict(os.environ, PYTHONFAULTHANDLER="1"),
            )
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(600):
            if self.closed:
                raise RuntimeError("启动已取消")
            if self.backend.poll() is not None:
                raise RuntimeError("后台已退出，请查看 logs/native-backend.log")
            try:
                with op.open("http://127.0.0.1:18991/health", timeout=1) as f:
                    assert json.load(f)["ready"]
                break
            except (OSError, ValueError):
                time.sleep(0.3)
        else:
            raise TimeoutError("后台启动超时")
        cfg = json.loads((R / "client/receiver.json").read_text(encoding="utf8"))
        cfg["monitor_interval_s"] = 5
        with self.lock:
            if self.closed:
                raise RuntimeError("启动已取消")
            self.app = App(cfg)
        return self.app.parameter_request("GET")

    def close(self):
        with self.lock:
            self.closed = True
            app = self.app
            self.app = None
        try:
            if app:
                app.close()
        finally:
            if self.backend is not None and self.backend.poll() is None:
                self.backend.terminate()
                try:
                    self.backend.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.backend.kill()
                    self.backend.wait(timeout=5)
            if hasattr(self, "log"):
                self.log.close()


class Window:
    def __init__(self, root):
        self.root = root
        self.service = Service()
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.messages = __import__("queue").Queue()
        self.settings = None
        self.preview_session = None
        self.photo = None
        self.devices = []
        self.closing = False
        root.title("FlowHMR 动作捕捉")
        root.geometry("850x730")
        root.minsize(760, 600)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.status = tk.StringVar(value="正在启动本机后台，请稍候…")
        ttk.Label(root, textvariable=self.status, wraplength=800).pack(
            fill="x", padx=15, pady=10
        )
        inputs = ttk.LabelFrame(root, text="画面来源")
        inputs.pack(fill="x", padx=15, pady=4)
        self.kind = tk.StringVar(value="video")
        ttk.Radiobutton(inputs, text="视频", variable=self.kind, value="video").grid(
            row=0, column=0
        )
        ttk.Radiobutton(inputs, text="摄像头", variable=self.kind, value="camera").grid(
            row=0, column=1
        )
        self.port = tk.StringVar(value="39539")
        ttk.Label(inputs, text="Warudo端口").grid(row=0, column=2)
        ttk.Entry(inputs, textvariable=self.port, width=12).grid(row=0, column=3)
        self.path = tk.StringVar()
        ttk.Entry(inputs, textvariable=self.path, width=64).grid(
            row=1, column=0, columnspan=3, padx=5, pady=5, sticky="ew"
        )
        ttk.Button(inputs, text="选择视频", command=self.choose).grid(
            row=1, column=3, padx=5
        )
        self.camera = ttk.Combobox(inputs, state="readonly", width=60)
        self.camera.grid(row=2, column=0, columnspan=3, padx=5, pady=5, sticky="ew")
        ttk.Button(inputs, text="刷新摄像头", command=self.cameras).grid(
            row=2, column=3, padx=5
        )
        settings = ttk.LabelFrame(root, text="参数：停止采集后修改，再点击应用")
        settings.pack(fill="x", padx=15, pady=5)
        self.variables = {}
        self.fields = []
        specs = [
            ("playout_delay_ms","延迟预算(ms)",[200,300,400,500,600,700,800,1000]),
            ("sam_chunk_size","SAM批次",[1,2]),
            ("target_fps", "目标帧率", [20, 25, 30]),
            ("sam_stride", "SAM间隔", [1, 2, 3, 4, 5, 6]),
            ("body_decoder_layers", "身体层数", [1, 2, 3, 4, 5, 6]),
            ("ode_steps", "Flow步数", list(range(1, 17))),
            ("yolo_size", "检测尺寸", [416, 640]),
            ("hand_mode", "手部", ["off", "fast", "full"]),
            ("hand_decoder_layers", "手部层数", [1, 2, 3, 4, 5, 6]),
        ]
        for i, (key, label, values) in enumerate(specs):
            row, col = divmod(i, 4)
            ttk.Label(settings, text=label).grid(
                row=row * 2, column=col, padx=12, pady=3
            )
            var = tk.StringVar()
            box = ttk.Combobox(
                settings, textvariable=var, values=values, state="readonly", width=16
            )
            box.grid(row=row * 2 + 1, column=col, padx=12, pady=3)
            self.variables[key] = var
            self.fields.append(box)
        buttons = ttk.Frame(root)
        buttons.pack(fill="x", padx=15, pady=8)
        self.apply_button = ttk.Button(buttons, text="应用参数", command=self.apply)
        self.apply_button.pack(side="left", padx=4)
        ttk.Button(buttons, text="8GB低负载", command=self.light).pack(
            side="left", padx=4
        )
        self.start_button = ttk.Button(
            buttons, text="开始输出到 Warudo", command=self.start
        )
        self.start_button.pack(side="left", padx=8)
        self.stop_button = ttk.Button(buttons, text="停止采集", command=self.stop)
        self.stop_button.pack(side="left", padx=4)
        ttk.Button(buttons, text="退出软件", command=self.close).pack(side="right")
        content = ttk.Frame(root)
        content.pack(fill="both", expand=True, padx=15, pady=5)
        self.picture = ttk.Label(
            content, text="首帧预览：捕获成功后显示一张，后续保持静止", anchor="center"
        )
        self.picture.pack(side="left", fill="both", expand=True)
        self.numbers = tk.StringVar(value="数字监控每 5 秒刷新，无图表。")
        ttk.Label(
            content, textvariable=self.numbers, justify="left", wraplength=290
        ).pack(side="right", padx=15)
        ttk.Label(
            root,
            text="请先打开 Warudo 并加载已配置的角色。关闭此窗口会退出采集、转发和后台，不关闭 Warudo。",
        ).pack(pady=8)
        for b in [self.start_button, self.stop_button, self.apply_button]:
            b.state(["disabled"])
        self.submit(self.service.boot, self.loaded)
        root.after(100, self.drain)
        root.after(5000, self.refresh)

    def submit(self, work, done=None):
        def run():
            try:
                self.messages.put((done, work(), None))
            except Exception as e:  # noqa: BLE001 - worker failures must reach the UI
                self.messages.put((None, None, str(e)))

        self.pool.submit(run)

    def drain(self):
        while not self.messages.empty():
            fn, value, error = self.messages.get()
            if not self.closing:
                if error:
                    self.status.set("操作失败：" + error)
                    messagebox.showerror("提示", error, parent=self.root)
                elif fn:
                    fn(value)
        if not self.closing:
            self.root.after(100, self.drain)

    def loaded(self, data):
        self.settings = data
        for key, var in self.variables.items():
            var.set(str(data["values"][key]))
        self.status.set("已就绪。选择视频或摄像头后点击开始。")
        self.start_button.state(["!disabled"])
        self.apply_button.state(["!disabled"])

    def choose(self):
        path = filedialog.askopenfilename(
            parent=self.root,
            title="选择视频",
            filetypes=[("视频", "*.mp4 *.mkv *.mov *.avi *.webm"), ("所有文件", "*.*")],
        )
        if path:
            self.path.set(path)
            self.kind.set("video")

    def cameras(self):
        self.submit(list_cameras, self.got_cameras)

    def got_cameras(self, data):
        self.devices = data.get("devices", [])
        self.camera["values"] = [
            d["name"] + "（设备 " + str(d["index"]) + "）" for d in self.devices
        ]
        if self.devices:
            self.camera.current(0)
        else:
            self.status.set("没有找到摄像头，请检查连接。")

    def values(self):
        return {
            k: v.get() if k == "hand_mode" else int(v.get())
            for k, v in self.variables.items()
        }

    def light(self):
        for k, v in {
            "sam_stride": 6,
            "body_decoder_layers": 1,
            "ode_steps": 1,
            "yolo_size": 416,
            "hand_mode": "off",
            "hand_decoder_layers": 1,
        }.items():
            self.variables[k].set(str(v))
        self.status.set("已填入低负载草稿，请点击应用参数。")

    def apply(self):
        if self.settings:
            payload = {"revision": self.settings["revision"], "values": self.values()}
            self.submit(
                lambda: self.service.app.apply_parameters(payload), self.applied
            )

    def applied(self, result):
        self.loaded(result)
        self.status.set("参数已保存，下次开始生效。")

    def start(self):
        if not self.settings:
            return
        if self.values() != self.settings["values"]:
            messagebox.showinfo("提示", "请先应用修改后的参数。", parent=self.root)
            return
        params = {
            "kind": self.kind.get(),
            "source": self.path.get(),
            "codec": "h264",
            "max_edge": 960,
            "bitrate_kbps": 1500,
        }
        if params["kind"] == "camera":
            index = self.camera.current()
            if index < 0:
                messagebox.showinfo("提示", "请先刷新并选择摄像头。", parent=self.root)
                return
            d = self.devices[index]
            params.update(source=str(d["index"]), camera_name=d["name"])
        self.start_button.state(["disabled"])
        port = self.port.get()
        self.status.set("正在准备输入；首次模型预热可能需要较长时间…")

        def work():
            app = self.service.app
            app.cfg["output_fps"] = self.settings["values"]["target_fps"]
            app.start_receiver(port)
            try:
                app.start_capture(params)
            except Exception:
                app.stop_receiver()
                raise

        self.submit(work)
        self.stop_button.state(["!disabled"])

    def stop(self):
        if self.service.app:
            self.service.app.stop_capture()
            self.service.app.stop_receiver()
            self.status.set("正在停止采集…")

    def refresh(self):
        if self.closing:
            return
        app = self.service.app
        if app:
            s = app.snapshot()
            c = s["client"]
            t = s["server"].get("telemetry", {})
            r = s["receiver"]
            active = c.get("thread_active", False)
            self.status.set(
                "采集："
                + {
                    "stopped": "等待采集",
                    "streaming": "正在输出动作",
                    "warming_up": "模型预热中",
                    "preprocessing": "准备视频中",
                    "connecting": "连接本机中",
                    "stopping": "正在停止",
                }.get(c.get("state"), c.get("state", ""))
                + "　"
                + (t.get("error") or c.get("error") or "")
            )
            self.numbers.set(
                f"上传：{c.get('upload_fps', 0)} FPS\n动作输出：{r.get('udp_fps', 0)} FPS\n引擎延迟：{t.get('measured_latency_ms', 0)} ms\n欠载累计：{t.get('underruns', 0)}\n检测：{t.get('yolox_ms_per_frame', 0)} ms/帧\nSAM：{t.get('sam_ms_per_frame', 0)} ms/帧\nFlow：{t.get('mmdit_ms_per_window', 0)} ms/窗口"
            )
            self.start_button.state(
                ["disabled" if active or s["server"].get("running") else "!disabled"]
            )
            self.stop_button.state(["!disabled" if active else "disabled"])
            self.apply_button.state(
                ["disabled" if active or s["server"].get("running") else "!disabled"]
            )
            if (
                c.get("preview_ready")
                and c.get("preview_session") != self.preview_session
            ):
                with app.lock:
                    data = app.preview
                image = Image.open(io.BytesIO(data))
                image.thumbnail((450, 240))
                self.photo = ImageTk.PhotoImage(image)
                self.picture.configure(image=self.photo, text="")
                self.preview_session = c["preview_session"]
        self.root.after(5000, self.refresh)

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.status.set("正在退出采集和后台，请稍候…")

        def shutdown():
            try:
                self.service.close()
            finally:
                self.root.after(0, self.root.destroy)

        threading.Thread(target=shutdown, daemon=True).start()


def main():
    root = tk.Tk()
    window = Window(root)
    try:
        root.mainloop()
    finally:
        window.service.close()
        window.pool.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        (R / "logs/native-ui-error.log").write_text(
            traceback.format_exc(), encoding="utf8"
        )
        try:
            messagebox.showerror("启动失败", traceback.format_exc())
        except tk.TclError:
            print("Tk error dialog unavailable", file=sys.stderr)
        raise
