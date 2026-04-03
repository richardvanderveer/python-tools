"""
AudioForge 2.0.0 – Audio Converter & Editor
Windows 11 – Python 3.14 compatible
Drag-drop via tkinterdnd2
"""
# ── Watermerk ────────────────────────────────────────────────
__author__    = "Richard van der Veer"
__version__   = "2.0.0"
__build__     = "2026-04-03"
__copyright__ = "© 2026 Richard van der Veer — github.com/richardvanderveer"
__watermark__ = "RVDV-AUDIOFORGE-2026-PYTHON-TOOLS"

import os, sys, shutil, subprocess, threading, tempfile, struct, math, time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ── numpy ─────────────────────────────────────────────────────────────────────
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

# ── tkinterdnd2 ───────────────────────────────────────────────────────────────
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
except ImportError:
    HAS_DND = False
    TkinterDnD = None

# ── ffmpeg (UC-11) ────────────────────────────────────────────────────────────
def _find(name):
    base = os.path.dirname(sys.executable if getattr(sys, 'frozen', False)
                           else os.path.abspath(__file__))
    for c in (name, name + '.exe'):
        p = os.path.join(base, c)
        if os.path.isfile(p): return p
    return shutil.which(name)

FFMPEG  = _find('ffmpeg')
FFPROBE = _find('ffprobe')
FFPLAY  = _find('ffplay')
SUPPORTED = ('.ogg', '.mp3', '.wav', '.m4a', '.flac', '.aac', '.mp4')
BITRATES  = ['64k', '96k', '128k', '192k', '256k', '320k']

def check_ffmpeg():
    miss = [n for n, p in [('ffmpeg', FFMPEG), ('ffprobe', FFPROBE)] if not p]
    if miss:
        messagebox.showerror('ffmpeg niet gevonden',
            f"{', '.join(miss)} niet gevonden.\n"
            'Download: https://ffmpeg.org/download.html\n'
            'Zet ffmpeg.exe + ffprobe.exe + ffplay.exe naast de exe.')
        sys.exit(1)

def get_duration(path):
    try:
        _flags = 0x08000000 if sys.platform == 'win32' else 0
        r = subprocess.run(
            [FFPROBE, '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', path],
            capture_output=True, text=True, timeout=15, creationflags=_flags)
        return float(r.stdout.strip())
    except:
        return 0.0

def s2hms(s):
    s = max(0, int(s)); h, r = divmod(s, 3600); m, sec = divmod(r, 60)
    return f'{h:02d}:{m:02d}:{sec:02d}'

def hms2s(t):
    p = t.strip().split(':')
    try:
        if len(p) == 3: return int(p[0])*3600 + int(p[1])*60 + float(p[2])
        if len(p) == 2: return int(p[0])*60 + float(p[1])
        return float(p[0])
    except:
        return 0.0

def ffbg(*args, on_done=None, on_error=None):
    def _r():
        _flags = 0x08000000 if sys.platform == 'win32' else 0
        try:
            subprocess.run([FFMPEG, '-y', *args], capture_output=True, check=True,
                           creationflags=_flags)
            if on_done: on_done()
        except subprocess.CalledProcessError as e:
            if on_error: on_error(e.stderr.decode(errors='replace'))
    threading.Thread(target=_r, daemon=True).start()

# ── waveform loader ───────────────────────────────────────────────────────────
def load_waveform(path, n=1600):
    if not FFMPEG: return None
    try:
        _flags = 0x08000000 if sys.platform == 'win32' else 0
        r = subprocess.run(
            [FFMPEG, '-v', 'quiet', '-i', path,
             '-f', 'f32le', '-ac', '1', '-ar', '8000', 'pipe:1'],
            capture_output=True, timeout=60, creationflags=_flags)
        raw = r.stdout
        if not raw or len(raw) < 4: return None
        if HAS_NUMPY:
            d  = np.frombuffer(raw, dtype=np.float32)
            bs = max(1, len(d) // n)
            d  = d[:bs * (len(d) // bs)].reshape(-1, bs)
            pk = np.abs(d).max(axis=1)
            mx = pk.max() or 1.0
            return (pk / mx).tolist()
        else:
            cnt = len(raw) // 4
            fl  = struct.unpack(f'{cnt}f', raw[:cnt*4])
            bs  = max(1, cnt // n)
            pk  = [max(abs(v) for v in fl[i*bs:(i+1)*bs])
                   for i in range(min(n, cnt // bs))]
            mx  = max(pk) or 1.0
            return [v / mx for v in pk]
    except:
        return None

# ── player via sounddevice ────────────────────────────────────────────────────
try:
    import sounddevice as sd
    import soundfile as sf
    HAS_SD = True
except ImportError:
    HAS_SD = False

class Player:
    """
    Speelt audio via sounddevice + ffmpeg decode.
    Geeft exacte positie en volume-controle.
    """
    def __init__(self):
        self._stream  = None
        self._data    = None   # numpy float32 array (frames, ch)
        self._sr      = 44100
        self._pos     = 0      # huidige frame
        self._active  = False
        self._vol     = 1.0
        self._dur     = 0.0
        self._tmp     = None
        self._lock    = threading.Lock()

    def set_volume(self, v):
        self._vol = max(0.0, min(1.0, float(v)))

    def play(self, path, offset=0.0):
        self._stop_stream()
        self._active  = True
        self._pos     = 0
        self._data    = None
        self._offset  = offset        # bewaar offset voor wall-clock fallback
        self._t_start = time.time()   # wall-clock start
        threading.Thread(target=self._decode, args=(path, offset), daemon=True).start()

    def stop(self):
        self._active = False
        self._stop_stream()
        self._cleanup_tmp()

    def playing(self):
        return self._active

    def pos(self):
        if not self._active:
            return None
        if self._data is not None and self._sr > 0:
            # Exacte positie via frame-teller
            return self._pos / self._sr
        else:
            # Nog aan het decoderen: schat via wall-clock
            return self._offset + (time.time() - self._t_start)

    def dur(self):
        return self._dur

    # ── intern ────────────────────────────────────────────────────────────────
    def _stop_stream(self):
        with self._lock:
            if self._stream is not None:
                try:
                    self._stream.abort(ignore_errors=True)
                    self._stream.close(ignore_errors=True)
                except Exception:
                    pass
                self._stream = None

    def _cleanup_tmp(self):
        if self._tmp and os.path.isfile(self._tmp):
            try: os.unlink(self._tmp)
            except: pass
        self._tmp = None

    def _decode(self, path, offset):
        """Achtergrondthread: ffmpeg → tijdelijke WAV → numpy → stream."""
        try:
            tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            tmp.close()
            self._tmp = tmp.name

            _flags = 0x08000000 if sys.platform == 'win32' else 0
            result = subprocess.run(
                [FFMPEG, '-y', '-v', 'quiet',
                 '-i', path,
                 '-f', 'wav', '-ar', '44100', '-ac', '2',
                 self._tmp],
                capture_output=True,
                creationflags=_flags,
                timeout=120)

            if not self._active:
                self._cleanup_tmp()
                return

            if result.returncode != 0 or not os.path.isfile(self._tmp):
                self._active = False
                self._cleanup_tmp()
                return

            data, sr = sf.read(self._tmp, dtype='float32', always_2d=True)
            self._cleanup_tmp()

            if not self._active:
                return

            self._data = data
            self._sr   = sr
            self._dur  = len(data) / sr
            # spring naar offset
            start_frame = max(0, min(int(offset * sr), len(data) - 1))
            self._pos   = start_frame

            self._start_stream()

        except Exception as exc:
            self._active = False
            self._cleanup_tmp()

    def _start_stream(self):
        if not self._active or self._data is None:
            return

        def _callback(outdata, frames, time_info, status):
            with self._lock:
                if not self._active or self._data is None:
                    outdata[:] = 0
                    raise sd.CallbackStop()
                end   = self._pos + frames
                chunk = self._data[self._pos:end]
                n     = len(chunk)
                if n > 0:
                    outdata[:n] = chunk * self._vol
                if n < frames:
                    outdata[n:] = 0
                    self._pos  += n
                    self._active = False
                    raise sd.CallbackStop()
                self._pos += frames

        try:
            with self._lock:
                self._stream = sd.OutputStream(
                    samplerate=self._sr,
                    channels=self._data.shape[1],
                    dtype='float32',
                    callback=_callback,
                    blocksize=1024,
                    finished_callback=lambda: None)
                self._stream.start()
        except Exception as exc:
            self._active = False


# ── themes ────────────────────────────────────────────────────────────────────
THEMES = {
    'dark': {
        'BG':'#1e1e1e', 'SURF':'#252526', 'SURF2':'#2d2d2d', 'SURF3':'#3a3a3a',
        'FG':'#d4d4d4', 'FGD':'#858585', 'ACC':'#0078d4', 'ACCFG':'#ffffff',
        'DANGER':'#c42b1c', 'BORDER':'#454545',
        'WAVE':'#4db8ff', 'WSEL':'#ffa040', 'CUR':'#ffffff',
        'TL':'#2d2d2d', 'MSEL':'#0078d4',
        'BTNBG':'#3a3a3a', 'BTNFG':'#cccccc', 'BTNACT':'#505050',
    },
    'light': {
        'BG':'#f0f0f0', 'SURF':'#ffffff', 'SURF2':'#f5f5f5', 'SURF3':'#e8e8e8',
        'FG':'#1a1a1a', 'FGD':'#666666', 'ACC':'#0067c0', 'ACCFG':'#ffffff',
        'DANGER':'#c42b1c', 'BORDER':'#cccccc',
        'WAVE':'#0067c0', 'WSEL':'#e07000', 'CUR':'#000000',
        'TL':'#e0e0e0', 'MSEL':'#0067c0',
        'BTNBG':'#e1e1e1', 'BTNFG':'#1a1a1a', 'BTNACT':'#c8c8c8',
    }
}

# ═════════════════════════════════════════════════════════════════════════════
class WaveCanvas(tk.Canvas):
    TLH = 20; HR = 5

    def __init__(self, master, app, **kw):
        super().__init__(master, bd=0, highlightthickness=0, **kw)
        self.app = app
        self.peaks = []; self.dur = 0.0
        self.z0 = 0.0; self.z1 = 1.0
        self.ss = None; self.se = None
        self._drag = None; self._x0 = 0
        self.cur = None

        self.bind('<Configure>',       lambda e: self.draw())
        self.bind('<ButtonPress-1>',   self._press)
        self.bind('<B1-Motion>',       self._move)
        self.bind('<ButtonRelease-1>', self._release)
        self.bind('<Button-3>',        self._rmenu)
        self.bind('<MouseWheel>',      self._wheel)

        self._menu = tk.Menu(self, tearoff=0)
        self._menu.add_command(label='✂  Knip fragment uit waveform',
                               command=lambda: app._cut_from_wave())
        self._menu.add_command(label='✂  Splitsen op startpunt',
                               command=lambda: app._split())
        self._menu.add_separator()
        self._menu.add_command(label='Selectie wissen', command=self._clr)

    def _W(self):  return max(1, self.winfo_width())
    def _H(self):  return max(1, self.winfo_height())
    def _WH(self): return self._H() - self.TLH

    def _x2f(self, x): return self.z0 + (x / self._W()) * (self.z1 - self.z0)
    def _f2x(self, f):
        sp = self.z1 - self.z0
        return 0 if sp == 0 else (f - self.z0) / sp * self._W()
    def _s2x(self, s): return self._f2x(s / self.dur) if self.dur else 0
    def _x2s(self, x): return max(0.0, min(self.dur, self._x2f(x) * self.dur))

    def load(self, peaks, dur):
        self.peaks = peaks or []; self.dur = dur
        self.z0 = 0.0; self.z1 = 1.0
        self.ss = self.se = self.cur = None
        self.draw()

    def clear(self):
        self.peaks = []; self.dur = 0.0
        self.ss = self.se = self.cur = None
        self.delete('all')

    def draw(self):
        T = self.app.T; W = self._W(); H = self._H(); WH = self._WH()
        self.delete('all')
        self.create_rectangle(0, 0, W, WH, fill=T['SURF2'], outline='')
        self.create_rectangle(0, WH, W, H,  fill=T['TL'],    outline='')

        if not self.peaks or not self.dur:
            self.create_text(W//2, WH//2,
                text='Selecteer een bestand om de audiogolf te laden',
                fill=T['FGD'], font=('Segoe UI', 10))
            return

        n = len(self.peaks); cx = WH // 2
        i0 = int(self.z0 * n); i1 = max(i0+1, min(n, int(self.z1*n)+1))
        vis = self.peaks[i0:i1]; nv = len(vis); bw = W / max(nv, 1)

        for idx, pk in enumerate(vis):
            x = idx * bw; ph = max(1.0, pk * (WH * 0.45))
            in_sel = (self.ss is not None and self.se is not None and
                      self._s2x(self.ss) <= x + bw/2 <= self._s2x(self.se))
            col = T['WSEL'] if in_sel else T['WAVE']
            if bw >= 2:
                self.create_rectangle(x, cx-ph, x+bw-1, cx+ph, fill=col, outline='')
            else:
                self.create_line(x, cx-ph, x, cx+ph, fill=col, width=1)

        self.create_line(0, cx, W, cx, fill=T['BORDER'], width=1)

        if self.ss is not None and self.se is not None:
            xs = self._s2x(self.ss); xe = self._s2x(self.se)
            self.create_rectangle(xs, 0, xe, WH,
                fill=T['WSEL'], stipple='gray25', outline='')
            self.create_line(xs, 0, xs, WH, fill=T['WSEL'], width=2)
            self.create_line(xe, 0, xe, WH, fill=T['WSEL'], width=2)
            for hx in (xs, xe):
                self.create_oval(hx-self.HR, cx-self.HR, hx+self.HR, cx+self.HR,
                    fill=T['ACC'], outline=T['SURF'])
            for hx, sec in [(xs, self.ss), (xe, self.se)]:
                lx = max(28, min(int(hx), W-28))
                self.create_rectangle(lx-26, 2, lx+26, 14, fill=T['SURF3'], outline='')
                self.create_text(lx, 8, text=s2hms(sec),
                    fill=T['ACC'], font=('Segoe UI', 7, 'bold'))

        if self.cur is not None:
            cx2 = self._s2x(self.cur)
            if 0 <= cx2 <= W:
                self.create_line(cx2, 0, cx2, WH, fill=T['CUR'], width=1, dash=(3, 3))

        self._draw_tl(WH, W)

    def _draw_tl(self, y, W):
        T = self.app.T; vd = (self.z1 - self.z0) * self.dur
        for iv in [.25, .5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800]:
            if vd / iv < W / 55: break
        t = math.ceil(self.z0 * self.dur / iv) * iv
        while t <= self.z1 * self.dur + .001:
            x = self._s2x(t)
            self.create_line(x, y, x, y+4, fill=T['FGD'])
            self.create_text(x, y+11, text=s2hms(t),
                fill=T['FGD'], font=('Segoe UI', 7), anchor='center')
            t += iv

    def _press(self, e):
        if not self.dur or e.y > self._WH(): return
        if self.ss is not None:
            if abs(e.x - self._s2x(self.ss)) <= self.HR + 4: self._drag = 'L'; return
            if abs(e.x - self._s2x(self.se)) <= self.HR + 4: self._drag = 'R'; return
        self._drag = 'N'; self._x0 = e.x
        s = self._x2s(e.x); self.ss = s; self.se = s
        self.draw(); self._notify()

    def _move(self, e):
        if not self._drag or not self.dur: return
        s = self._x2s(e.x)
        if   self._drag == 'N': a = self._x2s(self._x0); self.ss = min(a, s); self.se = max(a, s)
        elif self._drag == 'L': self.ss = min(s, self.se - .01)
        elif self._drag == 'R': self.se = max(s, self.ss + .01)
        self.config(cursor='sb_h_double_arrow' if self._drag in ('L','R') else 'crosshair')
        self.draw(); self._notify()

    def _release(self, e): self._drag = None; self.config(cursor='')

    def _rmenu(self, e):
        if self.ss is not None and self.se is not None:
            try: self._menu.tk_popup(e.x_root, e.y_root)
            finally: self._menu.grab_release()

    def _wheel(self, e):
        if not self.dur: return
        f = 0.75 if e.delta > 0 else 1.33
        c = self._x2f(e.x); sp = max(.005, min(1.0, (self.z1 - self.z0) * f))
        r = (c - self.z0) / max(self.z1 - self.z0, 1e-9)
        z0 = max(0.0, min(1.0 - sp, c - r * sp))
        self.z0 = z0; self.z1 = z0 + sp
        self.draw(); self.app.mm.draw_vp()

    def _clr(self): self.ss = self.se = None; self.draw(); self._notify()

    def _notify(self):
        if self.ss is not None:
            self.app.v_cs.set(s2hms(self.ss))
            self.app.v_ce.set(s2hms(self.se))
            self.app.v_sp.set(s2hms(self.ss))
            self.app.v_sel.set(
                f'{s2hms(self.ss)} → {s2hms(self.se)}  ({self.se - self.ss:.1f}s)')
        else:
            self.app.v_sel.set('—')

    def set_cur(self, pos):
        self.cur = pos
        if pos is not None and self.dur:
            f = pos / self.dur; sp = self.z1 - self.z0
            if f > self.z1 - sp * .05:
                # auto-scroll: full redraw nodig
                z0 = min(1 - sp, f - sp * .05); self.z0 = z0; self.z1 = z0 + sp
                self.app.mm.draw_vp()
                self.draw()
                return
            # Alleen cursor updaten: verwijder oude en teken nieuwe
            self.delete('cursor')
            if pos is not None:
                cx2 = self._s2x(pos)
                WH  = self._WH()
                if 0 <= cx2 <= self._W():
                    self.create_line(cx2, 0, cx2, WH,
                        fill=self.app.T['CUR'], width=2,
                        dash=(4, 3), tags='cursor')
        else:
            self.delete('cursor')


# ═════════════════════════════════════════════════════════════════════════════
class MiniMap(tk.Canvas):
    H = 30
    def __init__(self, master, app, wc, **kw):
        super().__init__(master, height=self.H, bd=0, highlightthickness=0, **kw)
        self.app = app; self.wc = wc; self._d = False
        self.bind('<Configure>',       lambda e: self.draw_full())
        self.bind('<ButtonPress-1>',   self._press)
        self.bind('<B1-Motion>',       self._move)
        self.bind('<ButtonRelease-1>', lambda e: setattr(self, '_d', False))

    def draw_full(self):
        T = self.app.T; W = max(1, self.winfo_width()); H = self.H
        self.delete('all')
        self.create_rectangle(0, 0, W, H, fill=T['SURF2'], outline='')
        if not self.wc.peaks: return
        n = len(self.wc.peaks); bw = W / n; cx = H // 2
        for i, p in enumerate(self.wc.peaks):
            x = i * bw; ph = max(1, p * (H * .42))
            self.create_line(x, cx-ph, x, cx+ph, fill=T['WAVE'], width=max(1, bw * .7))
        self.draw_vp()

    def draw_vp(self):
        T = self.app.T; W = max(1, self.winfo_width())
        self.delete('vp')
        x0 = self.wc.z0 * W; x1 = self.wc.z1 * W
        # Gevuld met stipple voor semi-transparant effect
        self.create_rectangle(x0, 0, x1, self.H,
            outline=T['ACC'], fill=T['ACC'], stipple='gray25', width=2, tags='vp')

    def _press(self, e): self._d = True; self._pan(e.x)
    def _move(self, e):
        if self._d: self._pan(e.x)
    def _pan(self, x):
        W = max(1, self.winfo_width()); c = x / W
        sp = self.wc.z1 - self.wc.z0
        z0 = max(0.0, min(1.0 - sp, c - sp / 2))
        self.wc.z0 = z0; self.wc.z1 = z0 + sp
        self.wc.draw(); self.draw_vp()


# ═════════════════════════════════════════════════════════════════════════════
# App – base class switches between TkinterDnD.Tk and tk.Tk
# ═════════════════════════════════════════════════════════════════════════════
_Base = TkinterDnD.Tk if HAS_DND else tk.Tk

class App(_Base):

    def __init__(self):
        super().__init__()
        check_ffmpeg()
        self._tn = 'dark'; self.T = THEMES['dark']

        self.title('AudioForge v4')
        self.geometry('1300x840'); self.minsize(1000, 680)
        self.configure(bg=self.T['BG'])

        # icon – zoek in _MEIPASS (gebundeld), naast exe, of naast script
        def _ico_path():
            for base in [
                getattr(sys, '_MEIPASS', None),
                os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else None,
                os.path.dirname(os.path.abspath(__file__)),
            ]:
                if base:
                    p = os.path.join(base, 'audioconvert.ico')
                    if os.path.isfile(p): return p
            return None
        _i = _ico_path()
        if _i:
            try: self.iconbitmap(_i)
            except: pass

        self.files = []; self.sel_idx = None
        self._pl = Player(); self._poll = None

        self._styles()
        self._ui()

        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self._dnd_drop)

        self.protocol('WM_DELETE_WINDOW', self._close)

    def _dnd_drop(self, event):
        import re
        raw = event.data
        paths = re.findall(r'\{([^}]+)\}|([^\s{}]+)', raw)
        paths = [a or b for a, b in paths]
        self._add_paths(paths)

    # ── styles ────────────────────────────────────────────────────────────────
    def _styles(self):
        T = self.T; s = ttk.Style(self); s.theme_use('clam')
        s.configure('.', background=T['BG'], foreground=T['FG'],
                    font=('Segoe UI', 9), borderwidth=0, relief='flat')
        s.configure('TFrame',  background=T['BG'])
        s.configure('TLabel',  background=T['BG'], foreground=T['FG'], font=('Segoe UI', 9))
        s.configure('TEntry',  fieldbackground=T['SURF3'], foreground=T['FG'],
                    insertcolor=T['FG'], borderwidth=1, relief='flat', padding=(4, 3))
        s.configure('TCombobox', fieldbackground=T['SURF3'], background=T['SURF3'],
                    foreground=T['FG'], arrowcolor=T['FG'],
                    selectbackground=T['ACC'], selectforeground=T['ACCFG'],
                    borderwidth=1, relief='flat')
        s.configure('Horizontal.TProgressbar',
                    troughcolor=T['SURF3'], background=T['ACC'],
                    borderwidth=0, thickness=4)
        s.configure('TScrollbar', background=T['SURF3'], troughcolor=T['SURF2'],
                    arrowcolor=T['FGD'], borderwidth=0)
        for nm, bg, fg, act in [
            ('W.TButton', T['BTNBG'], T['BTNFG'], T['BTNACT']),
            ('A.TButton', T['ACC'],   T['ACCFG'], T['SURF3']),
            ('D.TButton', T['DANGER'], '#fff',    '#a02020'),
        ]:
            s.configure(nm, background=bg, foreground=fg,
                        font=('Segoe UI', 9), padding=(10, 5),
                        borderwidth=1, relief='flat')
            s.map(nm, background=[('active', act), ('pressed', act)],
                  foreground=[('active', fg)])

    # ── UI ────────────────────────────────────────────────────────────────────
    def _ui(self):
        T = self.T
        hdr = tk.Frame(self, bg=T['SURF'], height=44)
        hdr.pack(fill='x'); hdr.pack_propagate(False)
        tk.Label(hdr, text='AudioForge', bg=T['SURF'], fg=T['FG'],
                 font=('Segoe UI', 14, 'bold')).pack(side='left', padx=16, pady=10)
        tk.Label(hdr, text='v4  ·  audio converter & editor',
                 bg=T['SURF'], fg=T['FGD'],
                 font=('Segoe UI', 9)).pack(side='left', pady=14)
        if not HAS_DND:
            tk.Label(hdr,
                text='⚠  pip install tkinterdnd2  voor drag-drop',
                bg=T['SURF'], fg='#e08000',
                font=('Segoe UI', 8)).pack(side='left', padx=20)
        ttk.Button(hdr, text='Thema', style='W.TButton',
                   command=self._theme).pack(side='right', padx=12, pady=8)

        self.v_status = tk.StringVar(value='Klaar.')
        sb = tk.Frame(self, bg=T['SURF'], height=22)
        sb.pack(fill='x', side='bottom'); sb.pack_propagate(False)
        tk.Frame(sb, bg=T['BORDER'], height=1).pack(fill='x', side='top')
        tk.Label(sb, textvariable=self.v_status, bg=T['SURF'], fg=T['FGD'],
                 font=('Segoe UI', 8)).pack(side='left', padx=10, pady=3)

        main = tk.Frame(self, bg=T['BG']); main.pack(fill='both', expand=True)
        self._left(main); self._right(main)

    def _left(self, p):
        T = self.T
        lf = tk.Frame(p, bg=T['BG'], width=280)
        lf.pack(side='left', fill='y', padx=(10, 0), pady=10)
        lf.pack_propagate(False)

        hr = tk.Frame(lf, bg=T['BG']); hr.pack(fill='x', pady=(0, 4))
        tk.Label(hr, text='Bestanden', bg=T['BG'], fg=T['FG'],
                 font=('Segoe UI', 9, 'bold')).pack(side='left')
        ttk.Button(hr, text='Toevoegen', style='A.TButton',
                   command=self._add).pack(side='right', padx=(4, 0))
        ttk.Button(hr, text='Leegmaken', style='W.TButton',
                   command=self._clear).pack(side='right')

        dnd_txt = ('Sleep bestanden hierheen' if HAS_DND
                   else 'Drag-drop: pip install tkinterdnd2')
        tk.Label(lf, text=dnd_txt, bg=T['BG'], fg=T['FGD'],
                 font=('Segoe UI', 8, 'italic')).pack(anchor='w', pady=(0, 3))

        lbf = tk.Frame(lf, bg=T['BORDER'], bd=1); lbf.pack(fill='both', expand=True)
        self.lb = tk.Listbox(lbf, bg=T['SURF2'], fg=T['FG'],
            selectbackground=T['ACC'], selectforeground=T['ACCFG'],
            activestyle='none', font=('Segoe UI', 9),
            borderwidth=0, highlightthickness=0)
        sb2 = ttk.Scrollbar(lbf, orient='vertical', command=self.lb.yview)
        self.lb.configure(yscrollcommand=sb2.set)
        sb2.pack(side='right', fill='y'); self.lb.pack(fill='both', expand=True)
        self.lb.bind('<<ListboxSelect>>', self._sel)

        of = tk.Frame(lf, bg=T['BG']); of.pack(fill='x', pady=(5, 0))
        ttk.Button(of, text='▲', style='W.TButton',
                   command=self._up).pack(side='left', padx=(0, 3))
        ttk.Button(of, text='▼', style='W.TButton',
                   command=self._dn).pack(side='left', padx=(0, 3))
        ttk.Button(of, text='Verwijder', style='D.TButton',
                   command=self._rm).pack(side='right')

    def _right(self, p):
        T = self.T
        rf = tk.Frame(p, bg=T['BG'])
        rf.pack(side='left', fill='both', expand=True, padx=10, pady=10)

        wc = tk.Frame(rf, bg=T['SURF'],
                      highlightbackground=T['BORDER'], highlightthickness=1)
        wc.pack(fill='x', pady=(0, 6))
        self.wv = WaveCanvas(wc, self, bg=T['SURF2'], height=160)
        self.wv.pack(fill='x', padx=4, pady=(4, 2))
        self.mm = MiniMap(wc, self, self.wv, bg=T['SURF3'])
        self.mm.pack(fill='x', padx=4, pady=(0, 2))

        # Rij 1: transport + volume
        pc = tk.Frame(wc, bg=T['SURF']); pc.pack(fill='x', padx=6, pady=(4, 2))
        ttk.Button(pc, text='▶ Afspelen', style='A.TButton',
                   command=self._play).pack(side='left', padx=(0, 3))
        ttk.Button(pc, text='▶ Vanaf selectie', style='W.TButton',
                   command=self._play_sel).pack(side='left', padx=(0, 3))
        ttk.Button(pc, text='■ Stop', style='W.TButton',
                   command=self._stop).pack(side='left', padx=(0, 12))
        tk.Label(pc, text='Vol:', bg=T['SURF'], fg=T['FGD'],
                 font=('Segoe UI', 8)).pack(side='left', padx=(8,2))
        self.v_vol = tk.IntVar(value=100)
        tk.Scale(pc, variable=self.v_vol,
                 from_=0, to=100, orient='horizontal',
                 length=140, showvalue=True, resolution=1,
                 bg=T['SURF'], fg=T['FGD'],
                 activebackground=T['ACC'],
                 troughcolor=T['SURF3'],
                 highlightthickness=1,
                 highlightbackground=T['BORDER'],
                 bd=1, sliderrelief='raised',
                 command=lambda v: self._pl.set_volume(float(v) / 100.0)
                 ).pack(side='left', padx=(0, 8))

        # Rij 2: voortgang
        pc2 = tk.Frame(wc, bg=T['SURF']); pc2.pack(fill='x', padx=6, pady=(0, 4))
        self._pb_canvas = tk.Canvas(pc2, height=8, bg=T['SURF3'],
            highlightthickness=0, bd=0)
        self._pb_canvas.pack(side='left', fill='x', expand=True, padx=(0, 8))
        self._pb_bar = self._pb_canvas.create_rectangle(
            0, 0, 0, 8, fill=T['ACC'], outline='')
        self._pb_canvas.bind('<Configure>',
            lambda e: self._pb_canvas.coords(self._pb_bar, 0, 0, 0, 8))
        self.v_playtime = tk.StringVar(value='')
        tk.Label(pc2, textvariable=self.v_playtime,
            bg=T['SURF'], fg=T['ACC'],
            font=('Segoe UI', 9, 'bold'), width=18).pack(side='left')

        # Rij 3: zoom
        pc3 = tk.Frame(wc, bg=T['SURF']); pc3.pack(fill='x', padx=6, pady=(0, 6))
        ttk.Button(pc3, text='+ Zoom', style='W.TButton',
                   command=lambda: self._zoom(.7)).pack(side='left', padx=(0, 2))
        ttk.Button(pc3, text='− Zoom', style='W.TButton',
                   command=lambda: self._zoom(1.4)).pack(side='left', padx=(0, 2))
        ttk.Button(pc3, text='Reset zoom', style='W.TButton',
                   command=self._zreset).pack(side='left')

        class _PBStub:
            def stop(self): pass
            def configure(self, **kw): pass
        self.pb = _PBStub()

        ir = tk.Frame(rf, bg=T['SURF'],
                      highlightbackground=T['BORDER'], highlightthickness=1)
        ir.pack(fill='x', pady=(0, 6))
        self.v_name = self._cell(ir, 'Bestand', '—')
        self.v_dur  = self._cell(ir, 'Duur',    '—')
        self.v_sel  = self._cell(ir, 'Selectie','—')

        ops = tk.Frame(rf, bg=T['BG']); ops.pack(fill='both', expand=True)
        c1 = tk.Frame(ops, bg=T['BG']); c1.pack(side='left', fill='both', expand=True, padx=(0,5))
        c2 = tk.Frame(ops, bg=T['BG']); c2.pack(side='left', fill='both', expand=True, padx=(0,5))
        c3 = tk.Frame(ops, bg=T['BG']); c3.pack(side='left', fill='both', expand=True)

        self._hdr(c1, 'Converteren')
        cv = self._card(c1)
        br = tk.Frame(cv, bg=T['SURF']); br.pack(fill='x', padx=8, pady=(6,4))
        tk.Label(br, text='Bitrate:', bg=T['SURF'], fg=T['FG'],
                 font=('Segoe UI', 9)).pack(side='left')
        self.v_br = tk.StringVar(value='192k')
        ttk.Combobox(br, textvariable=self.v_br, values=BITRATES,
                     width=7, state='readonly').pack(side='left', padx=6)
        bc = tk.Frame(cv, bg=T['SURF']); bc.pack(fill='x', padx=8, pady=(0,8))
        ttk.Button(bc, text='Geselecteerde → MP3', style='W.TButton',
                   command=self._conv1).pack(fill='x', pady=2)
        ttk.Button(bc, text='Alle bestanden → MP3', style='W.TButton',
                   command=self._convall).pack(fill='x', pady=2)
        ttk.Button(bc, text='Samenvoegen tot MP3', style='W.TButton',
                   command=self._merge).pack(fill='x', pady=2)

        self._hdr(c2, 'Fragment  (UC-09)')
        fc = self._card(c2)
        self.v_cs = self._trow(fc, 'Start:')
        self.v_ce = self._trow(fc, 'Einde:')
        ttk.Button(fc, text='💾  Sla fragment op', style='W.TButton',
                   command=self._save_fragment).pack(fill='x', padx=8, pady=(4,2))
        ttk.Button(fc, text='✂  Knip fragment uit waveform', style='W.TButton',
                   command=self._cut_from_wave).pack(fill='x', padx=8, pady=(0,8))

        self._hdr(c3, 'Splitsen  (UC-10)')
        sc = self._card(c3)
        self.v_sp = self._trow(sc, 'Splitspunt:')
        ttk.Button(sc, text='✂  Splits in 2 delen', style='W.TButton',
                   command=self._split).pack(fill='x', padx=8, pady=(4,8))

        self._hdr(c3, 'Uitvoermap')
        oc = self._card(c3)
        oi = tk.Frame(oc, bg=T['SURF']); oi.pack(fill='x', padx=8, pady=(6,8))
        self.v_out = tk.StringVar(value=os.path.expanduser('~\\Desktop'))
        ttk.Entry(oi, textvariable=self.v_out).pack(side='left', fill='x', expand=True)
        ttk.Button(oi, text='…', style='W.TButton', width=3,
                   command=self._pick_out).pack(side='left', padx=(4,0))

    def _hdr(self, p, t):
        T = self.T; f = tk.Frame(p, bg=T['BG']); f.pack(fill='x', pady=(6,2))
        tk.Label(f, text=t, bg=T['BG'], fg=T['FGD'],
                 font=('Segoe UI', 8, 'bold')).pack(side='left')
        tk.Frame(f, bg=T['BORDER'], height=1).pack(
            side='left', fill='x', expand=True, padx=5, pady=5)

    def _card(self, p):
        T = self.T
        c = tk.Frame(p, bg=T['SURF'],
                     highlightbackground=T['BORDER'], highlightthickness=1)
        c.pack(fill='x', pady=(0,4)); return c

    def _cell(self, p, lbl, val):
        T = self.T; c = tk.Frame(p, bg=T['SURF'])
        c.pack(side='left', fill='x', expand=True, padx=1, pady=1)
        tk.Label(c, text=lbl, bg=T['SURF'], fg=T['FGD'],
                 font=('Segoe UI', 7)).pack(anchor='w', padx=8, pady=(4,0))
        v = tk.StringVar(value=val)
        tk.Label(c, textvariable=v, bg=T['SURF'], fg=T['FG'],
                 font=('Segoe UI', 9, 'bold')).pack(anchor='w', padx=8, pady=(0,4))
        return v

    def _trow(self, p, lbl):
        T = self.T; r = tk.Frame(p, bg=T['SURF']); r.pack(fill='x', padx=8, pady=2)
        tk.Label(r, text=lbl, bg=T['SURF'], fg=T['FG'],
                 font=('Segoe UI', 9), width=10, anchor='w').pack(side='left')
        v = tk.StringVar(value='00:00:00')
        ttk.Entry(r, textvariable=v, width=11).pack(side='left'); return v

    # ── theme ─────────────────────────────────────────────────────────────────
    def _theme(self):
        self._tn = 'light' if self._tn == 'dark' else 'dark'
        self.T = THEMES[self._tn]; self._styles()
        for w in self.winfo_children(): w.destroy()
        self.configure(bg=self.T['BG']); self._ui()
        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self._dnd_drop)

    # ── files ─────────────────────────────────────────────────────────────────
    def _add(self):
        ps = filedialog.askopenfilenames(
            title='Audiobestanden toevoegen',
            filetypes=[('Audio', ' '.join(f'*{e}' for e in SUPPORTED)),
                       ('Alle bestanden', '*.*')])
        self._add_paths(list(ps))

    def _add_paths(self, paths):
        added = 0
        for p in paths:
            p = p.strip()
            if not p or os.path.splitext(p)[1].lower() not in SUPPORTED: continue
            if any(f['path'] == p for f in self.files): continue
            dur = get_duration(p)
            self.files.append({'path': p, 'name': os.path.basename(p), 'dur': dur})
            added += 1
        self._rlb(); self._st(f'{added} bestand(en) toegevoegd.')

    def _rlb(self):
        self.lb.delete(0, tk.END)
        for f in self.files:
            self.lb.insert(tk.END, f"  {f['name']}  [{s2hms(f['dur'])}]")

    def _sel(self, _=None):
        s = self.lb.curselection()
        if not s: return
        i = s[0]; self.sel_idx = i; f = self.files[i]
        self.v_name.set(f['name']); self.v_dur.set(s2hms(f['dur']))
        self.v_sel.set('—'); self.v_ce.set(s2hms(f['dur']))
        self._st(f"Audiogolf laden: {f['name']} …")
        self.wv.clear(); self.mm.delete('all')
        threading.Thread(target=self._load_bg,
                         args=(f['path'], f['dur']), daemon=True).start()

    def _load_bg(self, path, dur):
        pk = load_waveform(path)
        self.after(0, lambda: self._wave_ready(pk, dur))

    def _wave_ready(self, pk, dur):
        if pk:
            self.wv.load(pk, dur); self.mm.draw_full(); self._st('Klaar.')
        else:
            self._st('⚠  Audiogolf laden mislukt.')

    def _rm(self):
        if self.sel_idx is None or self.sel_idx >= len(self.files): return
        self.files.pop(self.sel_idx); self.sel_idx = None; self._rlb()
        self.v_name.set('—'); self.v_dur.set('—'); self.v_sel.set('—')
        self.wv.clear(); self.mm.delete('all')

    def _clear(self):
        if not self.files: return
        if messagebox.askyesno('Leegmaken', 'Alle bestanden verwijderen?'):
            self.files.clear(); self.sel_idx = None; self._rlb()
            self.v_name.set('—'); self.v_dur.set('—'); self.v_sel.set('—')
            self.wv.clear(); self.mm.delete('all')

    def _up(self):
        i = self.sel_idx
        if i is None or i == 0: return
        self.files[i], self.files[i-1] = self.files[i-1], self.files[i]
        self.sel_idx = i - 1; self._rlb(); self.lb.selection_set(self.sel_idx)

    def _dn(self):
        i = self.sel_idx
        if i is None or i >= len(self.files)-1: return
        self.files[i], self.files[i+1] = self.files[i+1], self.files[i]
        self.sel_idx = i + 1; self._rlb(); self.lb.selection_set(self.sel_idx)

    # ── zoom ──────────────────────────────────────────────────────────────────
    def _zoom(self, f):
        wv = self.wv; c = (wv.z0 + wv.z1) / 2
        sp = max(.005, min(1.0, (wv.z1 - wv.z0) * f))
        z0 = max(0.0, min(1.0 - sp, c - sp / 2))
        wv.z0 = z0; wv.z1 = z0 + sp; wv.draw(); self.mm.draw_vp()

    def _zreset(self):
        self.wv.z0 = 0.0; self.wv.z1 = 1.0; self.wv.draw(); self.mm.draw_vp()

    # ── playback ──────────────────────────────────────────────────────────────
    def _play(self):
        f = self._gf()
        if not f: return
        self._pl.play(f['path'])
        self._pb_canvas.coords(self._pb_bar, 0, 0, 0, 8)
        self.v_playtime.set(f"▶  {s2hms(0)} / {s2hms(f['dur'])}")
        self._st(f"▶  {f['name']}")
        self._tick()

    def _play_sel(self):
        f = self._gf()
        if not f: return
        off = float(self.wv.ss) if self.wv.ss is not None else 0.0
        self._pl.play(f['path'], off)
        self._pb_canvas.coords(self._pb_bar, 0, 0, 0, 8)
        self.v_playtime.set(f"▶  {s2hms(off)} / {s2hms(f['dur'])}")
        self._st(f'▶  vanaf {s2hms(off)}')
        self._tick()

    def _tick(self):
        if self._poll: self.after_cancel(self._poll)
        self.__tick()

    def __tick(self):
        # Zolang player actief is blijven we tiken
        if not self._pl._active:
            # Afspelen klaar
            if self.wv.dur:
                self.wv.set_cur(None); self.wv.draw()
            self._pb_canvas.coords(self._pb_bar, 0, 0, 0, 8)
            self.v_playtime.set('')
            self._st('Klaar.')
            return

        pos = self._pl.pos()
        dur = self.wv.dur or (
            self.files[self.sel_idx].get('dur', 0)
            if self.sel_idx is not None and self.sel_idx < len(self.files)
            else 0)

        if pos is not None and dur:
            # waveform cursor (lichtgewicht: alleen cursor tag, geen full redraw)
            if self.wv.dur:
                self.wv.set_cur(pos)
            # voortgangsbalk (gebruik canvas breedte via winfo)
            self.update_idletasks()
            w = self._pb_canvas.winfo_width()
            if w > 1:
                self._pb_canvas.coords(self._pb_bar,
                    0, 0, int(w * min(1.0, pos / dur)), 8)
            # tijdlabel
            self.v_playtime.set(f"{s2hms(pos)} / {s2hms(dur)}")
        else:
            self.v_playtime.set('laden…')

        # Altijd doorgaan zolang actief
        self._poll = self.after(100, self.__tick)

    def _stop(self):
        self._pl.stop()
        if self._poll: self.after_cancel(self._poll)
        if self.wv.dur:
            self.wv.set_cur(None); self.wv.draw()
        self._pb_canvas.coords(self._pb_bar, 0, 0, 0, 8)
        self.v_playtime.set('')
        self._st('Gestopt.')

    # ── convert ───────────────────────────────────────────────────────────────
    def _conv1(self):
        f = self._gf()
        if not f: return
        out = os.path.join(self._od(), os.path.splitext(f['name'])[0] + '.mp3')
        self._st(f"Converteren: {f['name']} …")
        ffbg('-i', f['path'], '-b:a', self.v_br.get(), out,
            on_done=lambda: self.after(0, lambda: self._done(f'✓  {os.path.basename(out)}')),
            on_error=lambda e: self.after(0, lambda: self._err(e)))

    def _convall(self):
        if not self.files: messagebox.showinfo('Leeg', 'Geen bestanden.'); return
        br, od = self.v_br.get(), self._od()
        self._st(f'Batch {len(self.files)} bestanden …')
        def _b():
            errs = []
            for f in self.files:
                out = os.path.join(od, os.path.splitext(f['name'])[0] + '.mp3')
                try:
                    subprocess.run([FFMPEG, '-y', '-i', f['path'], '-b:a', br, out],
                                   capture_output=True, check=True,
                                   creationflags=0x08000000 if sys.platform=='win32' else 0)
                except: errs.append(f['name'])
            n = len(self.files)
            msg = (f'✓  {n-len(errs)}/{n} geconverteerd.' +
                   (f'\nFouten: {", ".join(errs)}' if errs else ''))
            self.after(0, lambda: self._done(msg))
            self.after(0, lambda: messagebox.showinfo('Batch klaar', msg))
        threading.Thread(target=_b, daemon=True).start()

    def _merge(self):
        if len(self.files) < 2:
            messagebox.showinfo('Te weinig', 'Minimaal 2 bestanden.'); return
        out = filedialog.asksaveasfilename(defaultextension='.mp3',
            filetypes=[('MP3', '*.mp3')])
        if not out: return
        self._st('Samenvoegen …')
        def _m():
            with tempfile.NamedTemporaryFile('w', suffix='.txt',
                                             delete=False, encoding='utf-8') as tf:
                for f in self.files: tf.write(f"file '{f['path']}'\n")
                tp = tf.name
            try:
                subprocess.run([FFMPEG, '-y', '-f', 'concat', '-safe', '0',
                                '-i', tp, '-b:a', self.v_br.get(), out],
                               capture_output=True, check=True,
                               creationflags=0x08000000 if sys.platform=='win32' else 0)
                self.after(0, lambda: self._done(f'✓  {os.path.basename(out)}'))
            except subprocess.CalledProcessError as e:
                err = e.stderr.decode(errors='replace')
                self.after(0, lambda: self._err(err))
            finally: os.unlink(tp)
        threading.Thread(target=_m, daemon=True).start()

    def _save_fragment(self):
        """Sla het geselecteerde fragment op als losse MP3 (origineel blijft intact)."""
        f = self._gf()
        if not f: return
        s = hms2s(self.v_cs.get()); e = hms2s(self.v_ce.get())
        if e <= s:
            messagebox.showerror('Tijdfout', 'Eindtijd moet na starttijd zijn.'); return
        out = filedialog.asksaveasfilename(defaultextension='.mp3',
            filetypes=[('MP3', '*.mp3'), ('Alle', '*.*')])
        if not out: return
        self._st('Fragment opslaan …')
        ffbg('-ss', str(s), '-t', str(e-s), '-i', f['path'],
            '-b:a', self.v_br.get(), out,
            on_done=lambda: self.after(0, lambda: self._done(f'✓  {os.path.basename(out)}')),
            on_error=lambda e2: self.after(0, lambda: self._err(e2)))

    def _cut_from_wave(self):
        """Knip fragment uit de audiogolf: bewaar deel voor en na selectie,
        voeg die samen en vervang het bestand in de werklijst."""
        f = self._gf()
        if not f: return
        s = hms2s(self.v_cs.get()); e = hms2s(self.v_ce.get())
        dur = f['dur']
        if e <= s:
            messagebox.showerror('Tijdfout', 'Eindtijd moet na starttijd zijn.'); return
        if s <= 0 and e >= dur:
            messagebox.showerror('Fout', 'Selectie beslaat het hele bestand.'); return
        if not messagebox.askyesno('Fragment uitknippen',
                f'Knip {s2hms(s)} \u2192 {s2hms(e)} uit "{f["name"]}"?\n'
                f'Het bestand in de werklijst wordt vervangen door het resultaat.'):
            return

        od   = self._od()
        base = os.path.splitext(f['name'])[0]
        out  = os.path.join(od, f'{base}_geknipt.mp3')
        self._st('Fragment uitknippen uit waveform …')
        _fl  = 0x08000000 if sys.platform == 'win32' else 0
        idx  = self.sel_idx

        def _do():
            try:
                parts = []
                # Deel vóór de selectie
                if s > 0.1:
                    p1 = os.path.join(od, f'__part1_{base}.mp3')
                    subprocess.run([FFMPEG, '-y', '-i', f['path'],
                                    '-t', str(s), '-b:a', self.v_br.get(), p1],
                                   capture_output=True, check=True, creationflags=_fl)
                    parts.append(p1)
                # Deel na de selectie
                if e < dur - 0.1:
                    p2 = os.path.join(od, f'__part2_{base}.mp3')
                    subprocess.run([FFMPEG, '-y', '-ss', str(e), '-i', f['path'],
                                    '-b:a', self.v_br.get(), p2],
                                   capture_output=True, check=True, creationflags=_fl)
                    parts.append(p2)

                if not parts:
                    self.after(0, lambda: self._err('Niets over na knippen.'))
                    return

                if len(parts) == 1:
                    # Alleen één deel: direct hernomen
                    os.replace(parts[0], out)
                else:
                    # Twee delen samenvoegen
                    with tempfile.NamedTemporaryFile('w', suffix='.txt',
                                                     delete=False, encoding='utf-8') as tf:
                        for p in parts: tf.write(f"file '{p}'\n")
                        tp = tf.name
                    subprocess.run([FFMPEG, '-y', '-f', 'concat', '-safe', '0',
                                    '-i', tp, '-b:a', self.v_br.get(), out],
                                   capture_output=True, check=True, creationflags=_fl)
                    os.unlink(tp)
                    for p in parts:
                        if os.path.isfile(p): os.unlink(p)

                # Vervang bestand in werklijst
                new_dur = get_duration(out)
                self.after(0, lambda: self._replace_file(idx, out, new_dur))

            except subprocess.CalledProcessError as ex:
                err = ex.stderr.decode(errors='replace')
                self.after(0, lambda: self._err(err))

        threading.Thread(target=_do, daemon=True).start()

    def _replace_file(self, idx, path, dur):
        """Vervang bestand in werklijst na uitknippen en herlaad waveform."""
        if idx >= len(self.files): return
        self.files[idx] = {
            'path': path,
            'name': os.path.basename(path),
            'dur':  dur
        }
        self._rlb()
        self.lb.selection_set(idx)
        self._st(f'✓  Geknipt opgeslagen: {os.path.basename(path)}')
        # Herlaad waveform
        self.wv.clear(); self.mm.delete('all')
        threading.Thread(target=self._load_bg,
                         args=(path, dur), daemon=True).start()

    def _split(self):
        f = self._gf()
        if not f: return
        at = hms2s(self.v_sp.get())
        if at <= 0 or at >= f['dur']:
            messagebox.showerror('Tijdfout', 'Splitspunt buiten bereik.'); return
        base = os.path.splitext(f['name'])[0]; od = self._od()
        o1 = os.path.join(od, f'{base}_deel1.mp3')
        o2 = os.path.join(od, f'{base}_deel2.mp3')
        self._st('Splitsen …')
        def _s():
            try:
                _fl = 0x08000000 if sys.platform == 'win32' else 0
                subprocess.run([FFMPEG, '-y', '-i', f['path'], '-t', str(at),
                                '-b:a', self.v_br.get(), o1],
                               capture_output=True, check=True, creationflags=_fl)
                subprocess.run([FFMPEG, '-y', '-ss', str(at), '-i', f['path'],
                                '-b:a', self.v_br.get(), o2],
                               capture_output=True, check=True, creationflags=_fl)
                msg = (f'✓  Deel 1: {os.path.basename(o1)}\n'
                       f'   Deel 2: {os.path.basename(o2)}')
                self.after(0, lambda: self._done(msg))
                self.after(0, lambda: messagebox.showinfo('Gesplitst', msg))
            except subprocess.CalledProcessError as e:
                err = e.stderr.decode(errors='replace')
                self.after(0, lambda: self._err(err))
        threading.Thread(target=_s, daemon=True).start()

    # ── utils ─────────────────────────────────────────────────────────────────
    def _pick_out(self):
        d = filedialog.askdirectory()
        if d: self.v_out.set(d)

    def _od(self):
        d = self.v_out.get(); os.makedirs(d, exist_ok=True); return d

    def _gf(self):
        if self.sel_idx is None or self.sel_idx >= len(self.files):
            messagebox.showinfo('Geen selectie', 'Selecteer eerst een bestand.')
            return None
        return self.files[self.sel_idx]

    def _st(self, m):   self.v_status.set(m); self.update_idletasks()
    def _done(self, m): self.pb.stop(); self._st(m)
    def _err(self, d):  self.pb.stop(); self._st('⚠  Fout.'); messagebox.showerror('Fout', d[:600])
    def _close(self):   self._pl.stop(); self.destroy()


if __name__ == '__main__':
    app = App()
    app.mainloop()