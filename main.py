import io
import json
import threading
import urllib.request
from pathlib import Path
from datetime import datetime

import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image
import yt_dlp

APP_NAME = "YT Downloader"
CONFIG_DIR = Path.home() / ".ytdownloader"
HISTORY_FILE = CONFIG_DIR / "history.json"
DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads" / "YTDownloader"

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


def ensure_dirs():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


def load_history():
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except Exception:
            return []
    return []


def save_history(history):
    try:
        HISTORY_FILE.write_text(json.dumps(history, indent=2))
    except Exception:
        pass


class YTDownloaderApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ensure_dirs()
        self.title(APP_NAME)
        self.geometry("720x660")
        self.minsize(640, 580)

        self.output_dir = DEFAULT_DOWNLOAD_DIR
        self.current_info = None
        self.quality_map = {}  # label -> format selector fragment
        self.history = load_history()

        self._build_ui()
        self._refresh_history_list()

    # ---------- UI ----------
    def _build_ui(self):
        pad = 12

        url_frame = ctk.CTkFrame(self)
        url_frame.pack(fill="x", padx=pad, pady=(pad, 6))

        self.url_entry = ctk.CTkEntry(url_frame, placeholder_text="Paste YouTube URL here...")
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(8, 8), pady=8)

        self.fetch_btn = ctk.CTkButton(url_frame, text="Fetch Info", width=110, command=self.on_fetch)
        self.fetch_btn.pack(side="left", padx=(0, 8), pady=8)

        self.thumbnail_image = None  # keep a reference so it isn't garbage collected
        self.thumbnail_label = ctk.CTkLabel(self, text="", height=180)
        self.thumbnail_label.pack(padx=pad, pady=(0, 6))

        self.info_label = ctk.CTkLabel(self, text="Paste a link and click Fetch Info.",
                                        wraplength=680, justify="left", anchor="w")
        self.info_label.pack(fill="x", padx=pad, pady=(0, 6))

        options_frame = ctk.CTkFrame(self)
        options_frame.pack(fill="x", padx=pad, pady=6)

        ctk.CTkLabel(options_frame, text="Quality:").pack(side="left", padx=(8, 4), pady=8)
        self.quality_var = ctk.StringVar(value="Fetch a video first")
        self.quality_menu = ctk.CTkOptionMenu(options_frame, variable=self.quality_var,
                                               values=["Fetch a video first"], width=260)
        self.quality_menu.pack(side="left", padx=4, pady=8)

        self.audio_only_var = ctk.BooleanVar(value=False)
        self.audio_check = ctk.CTkCheckBox(options_frame, text="Audio only (MP3)",
                                            variable=self.audio_only_var,
                                            command=self.on_toggle_audio_only)
        self.audio_check.pack(side="left", padx=12, pady=8)

        out_frame = ctk.CTkFrame(self)
        out_frame.pack(fill="x", padx=pad, pady=6)

        self.out_label = ctk.CTkLabel(out_frame, text=f"Save to: {self.output_dir}", anchor="w")
        self.out_label.pack(side="left", fill="x", expand=True, padx=8, pady=8)

        self.choose_dir_btn = ctk.CTkButton(out_frame, text="Choose Folder", width=120,
                                             command=self.on_choose_dir)
        self.choose_dir_btn.pack(side="right", padx=8, pady=8)

        self.download_btn = ctk.CTkButton(self, text="Download", command=self.on_download,
                                           state="disabled", height=38)
        self.download_btn.pack(fill="x", padx=pad, pady=(6, 4))

        self.progress_bar = ctk.CTkProgressBar(self)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", padx=pad, pady=(0, 4))

        self.status_label = ctk.CTkLabel(self, text="", anchor="w")
        self.status_label.pack(fill="x", padx=pad, pady=(0, 6))

        ctk.CTkLabel(self, text="Download History", anchor="w",
                     font=ctk.CTkFont(weight="bold")).pack(fill="x", padx=pad, pady=(6, 0))

        self.history_box = ctk.CTkTextbox(self, height=160)
        self.history_box.pack(fill="both", expand=True, padx=pad, pady=(4, pad))
        self.history_box.configure(state="disabled")

    # ---------- Helpers ----------
    def set_status(self, text):
        self.status_label.configure(text=text)

    def _refresh_history_list(self):
        self.history_box.configure(state="normal")
        self.history_box.delete("1.0", "end")
        if not self.history:
            self.history_box.insert("end", "No downloads yet.")
        else:
            for entry in reversed(self.history[-50:]):
                line = f"[{entry['time']}] {entry['title']} \u2014 {entry['quality']} \u2192 {entry['path']}\n"
                self.history_box.insert("end", line)
        self.history_box.configure(state="disabled")

    def on_choose_dir(self):
        chosen = filedialog.askdirectory(initialdir=str(self.output_dir))
        if chosen:
            self.output_dir = Path(chosen)
            self.out_label.configure(text=f"Save to: {self.output_dir}")

    def on_toggle_audio_only(self):
        self.quality_menu.configure(state="disabled" if self.audio_only_var.get() else "normal")

    # ---------- Fetch ----------
    def on_fetch(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning(APP_NAME, "Please paste a YouTube URL first.")
            return
        self.fetch_btn.configure(state="disabled", text="Fetching...")
        self.download_btn.configure(state="disabled")
        self.set_status("Fetching video info...")
        self.info_label.configure(text="Fetching video info...")
        self.thumbnail_label.configure(image=None, text="")
        self.thumbnail_image = None
        threading.Thread(target=self._fetch_worker, args=(url,), daemon=True).start()

    def _fetch_worker(self, url):
        try:
            ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            self.after(0, self._fetch_failed, str(e))
            return

        thumb_img = self._download_thumbnail(info)
        self.after(0, self._fetch_done, info, thumb_img)

    def _download_thumbnail(self, info):
        """Best-effort thumbnail download; returns a PIL Image or None."""
        thumb_url = info.get("thumbnail")
        if not thumb_url and info.get("entries"):
            first = next((e for e in info["entries"] if e), None)
            thumb_url = first.get("thumbnail") if first else None
        if not thumb_url:
            return None
        try:
            req = urllib.request.Request(thumb_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
            img = Image.open(io.BytesIO(data))
            img.load()
            return img.convert("RGB")
        except Exception:
            return None

    def _fetch_failed(self, error_text):
        self.fetch_btn.configure(state="normal", text="Fetch Info")
        self.info_label.configure(text=f"Could not fetch video: {error_text}")
        self.thumbnail_label.configure(image=None, text="")
        self.thumbnail_image = None
        self.set_status("")

    def _fetch_done(self, info, thumb_img=None):
        self.fetch_btn.configure(state="normal", text="Fetch Info")

        if thumb_img is not None:
            display_w = 320
            display_h = int(thumb_img.height * (display_w / thumb_img.width))
            ctk_img = ctk.CTkImage(light_image=thumb_img, dark_image=thumb_img,
                                    size=(display_w, display_h))
            self.thumbnail_image = ctk_img
            self.thumbnail_label.configure(image=ctk_img, text="")
        else:
            self.thumbnail_label.configure(image=None, text="(no thumbnail available)")
            self.thumbnail_image = None

        if info.get("_type") == "playlist" or "entries" in info:
            entries = [e for e in info.get("entries", []) if e]
            if not entries:
                self._fetch_failed("Playlist appears to be empty.")
                return
            info = entries[0]
            self.info_label.configure(
                text=f"Playlist detected \u2014 using first video: {info.get('title', 'Unknown')}"
            )
        else:
            self.info_label.configure(text=f"{info.get('title', 'Unknown title')}")

        self.current_info = info

        heights = sorted({
            f.get("height") for f in info.get("formats", [])
            if f.get("height") and f.get("vcodec") != "none"
        }, reverse=True)

        self.quality_map = {"Best available (video+audio)": "best"}
        for h in heights:
            self.quality_map[f"{h}p"] = f"height<={h}"

        labels = list(self.quality_map.keys())
        self.quality_menu.configure(values=labels)
        self.quality_var.set(labels[0])
        self.download_btn.configure(state="normal")
        self.set_status("Ready to download.")

    # ---------- Download ----------
    def on_download(self):
        if not self.current_info:
            return
        url = self.url_entry.get().strip()
        audio_only = self.audio_only_var.get()
        quality_label = self.quality_var.get()
        quality_key = self.quality_map.get(quality_label, "best")

        self.download_btn.configure(state="disabled", text="Downloading...")
        self.fetch_btn.configure(state="disabled")
        self.progress_bar.set(0)
        self.set_status("Starting download...")

        threading.Thread(
            target=self._download_worker,
            args=(url, quality_key, quality_label, audio_only),
            daemon=True,
        ).start()

    def _progress_hook(self, d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes", 0)
            if total:
                self.after(0, self.progress_bar.set, downloaded / total)
            speed = d.get("speed")
            eta = d.get("eta")
            speed_str = f"{speed / 1024 / 1024:.2f} MB/s" if speed else "..."
            eta_str = f"{eta}s" if eta is not None else "..."
            self.after(0, self.set_status, f"Downloading... {speed_str}, ETA {eta_str}")
        elif d["status"] == "finished":
            self.after(0, self.set_status, "Processing (merging/converting)...")
            self.after(0, self.progress_bar.set, 1.0)

    def _download_worker(self, url, quality_key, quality_label, audio_only):
        outtmpl = str(self.output_dir / "%(title)s.%(ext)s")
        ydl_opts = {
            "outtmpl": outtmpl,
            "progress_hooks": [self._progress_hook],
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }

        if audio_only:
            ydl_opts["format"] = "bestaudio/best"
            ydl_opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        elif quality_key == "best":
            ydl_opts["format"] = "bestvideo+bestaudio/best"
            ydl_opts["merge_output_format"] = "mp4"
        else:
            ydl_opts["format"] = f"bestvideo[{quality_key}]+bestaudio/best[{quality_key}]"
            ydl_opts["merge_output_format"] = "mp4"

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                result_info = ydl.extract_info(url, download=True)
                final_path = ydl.prepare_filename(result_info)
                if audio_only:
                    final_path = str(Path(final_path).with_suffix(".mp3"))
        except Exception as e:
            self.after(0, self._download_failed, str(e))
            return

        self.after(0, self._download_done, result_info, final_path,
                   "Audio (MP3)" if audio_only else quality_label)

    def _download_failed(self, error_text):
        self.download_btn.configure(state="normal", text="Download")
        self.fetch_btn.configure(state="normal")
        self.set_status(f"Download failed: {error_text}")
        messagebox.showerror(APP_NAME, f"Download failed:\n{error_text}")

    def _download_done(self, info, final_path, quality_label):
        self.download_btn.configure(state="normal", text="Download")
        self.fetch_btn.configure(state="normal")
        self.set_status("Download complete!")

        entry = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "title": info.get("title", "Unknown"),
            "quality": quality_label,
            "path": final_path,
        }
        self.history.append(entry)
        save_history(self.history)
        self._refresh_history_list()

        messagebox.showinfo(APP_NAME, f"Download complete!\nSaved to:\n{final_path}")


def main():
    app = YTDownloaderApp()
    app.mainloop()


if __name__ == "__main__":
    main()