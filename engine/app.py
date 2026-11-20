"""Bilingual desktop interface for full-book synchronization."""
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
from time import monotonic
import locale
import tkinter as tk
from tkinter import filedialog, ttk
from tkinter.scrolledtext import ScrolledText
import traceback

from devices import available_devices
from engine import generate


TEXT = {
    'subtitle': ('Align an entire audiobook with its EPUB.', 'Alinea el audiolibro completo con su EPUB.'),
    'language': ('Language', 'Idioma'),
    'epub': ('Text (EPUB)', 'Texto (EPUB)'),
    'audio_file': ('Audio', 'Audio'),
    'browse': ('Browse…', 'Examinar…'),
    'device': ('Processing device (CPU or GPU)', 'Dispositivo de procesamiento (CPU o GPU)'),
    'detect': ('Detecting devices…', 'Detectando dispositivos…'),
    'no_device': ('No usable CPU or GPU detected. Open the console for details.',
                  'No se detectó una CPU o GPU utilizable. Abre la consola para ver los detalles.'),
    'start': ('Synchronize', 'Sincronizar'),
    'cancel': ('Cancel', 'Cancelar'),
    'show': ('Show console', 'Mostrar consola'),
    'hide': ('Hide console', 'Ocultar consola'),
    'ready': ('Select the EPUB, the audio and a device.', 'Selecciona el EPUB, el audio y un dispositivo.'),
    'prepare': ('Reading the EPUB and audio metadata…', 'Leyendo los metadatos del EPUB y el audio…'),
    'model': ('Loading Whisper base…', 'Cargando Whisper base…'),
    'audio': ('Transcribing the audiobook…', 'Transcribiendo el audiolibro…'),
    'audio_detail': ('Audio: {0}/{1} s · {2} words recognized', 'Audio: {0}/{1} s · {2} palabras reconocidas'),
    'align': ('Aligning the full transcript with the EPUB…', 'Alineando la transcripción completa con el EPUB…'),
    'save': ('Saving the synchronization JSON…', 'Guardando el JSON de sincronización…'),
    'done': ('Finished · {0:,} of {1:,} EPUB words aligned', 'Terminado · {0:,} de {1:,} palabras del EPUB alineadas'),
    'saved': ('Saved to {0}', 'Guardado en {0}'),
    'cancelling': ('Cancelling…', 'Cancelando…'),
    'cancelled': ('Cancelled.', 'Cancelado.'),
    'error': ('Synchronization failed. See the console for details.', 'Falló la sincronización. Consulta la consola.'),
    'exists': ('An export already exists. Rename it to run again.', 'Ya existe una exportación. Renómbrala para repetir el proceso.'),
    'remaining': ('Estimated time left  {0}', 'Tiempo restante estimado  {0}'),
    'estimating': ('Estimating…', 'Calculando…'),
    'files': ('All files', 'Todos los archivos'),
    'running_on': ('Processing on {0} ({1})', 'Procesando en {0} ({1})'),
}


class Application(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Read & Listen — Sync Engine 3')
        self.minsize(560, 330)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        system_language = locale.getlocale()[0] or ''
        self.language = tk.StringVar(value='Español' if system_language.lower().startswith(('es', 'spanish')) else 'English')
        self.paths = {kind: tk.StringVar() for kind in ('epub', 'audio_file')}
        self.events = Queue()
        self.devices = []
        self.running = False
        self.console_visible = False
        self.log_entries = []
        self.status = ('detect', ())
        self.transcription_started = None
        self.estimate_end = None
        self.percent = tk.DoubleVar()
        self.labels = {}

        form = ttk.Frame(self, padding=18)
        form.grid(sticky='ew')
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text='Sync Engine 3', font=('Segoe UI', 21, 'bold')).grid(row=0, column=0, columnspan=2, sticky='w')
        language_bar = ttk.Frame(form)
        language_bar.grid(row=0, column=2, sticky='e')
        self.labels['language'] = ttk.Label(language_bar)
        self.labels['language'].pack(side='left', padx=(0, 6))
        language = ttk.Combobox(language_bar, textvariable=self.language, values=('English', 'Español'),
                                state='readonly', width=10)
        language.pack(side='left')
        language.bind('<<ComboboxSelected>>', lambda _: self.translate())
        self.labels['subtitle'] = ttk.Label(form)
        self.labels['subtitle'].grid(row=1, column=0, columnspan=3, sticky='w', pady=(2, 14))
        self.browse_buttons = {}
        for row, kind in enumerate(self.paths, 2):
            self.labels[kind] = ttk.Label(form)
            self.labels[kind].grid(row=row, column=0, sticky='w', padx=(0, 10))
            ttk.Entry(form, textvariable=self.paths[kind], state='readonly').grid(row=row, column=1, sticky='ew', pady=4)
            button = ttk.Button(form, command=lambda k=kind: self.browse(k))
            button.grid(row=row, column=2, sticky='w', padx=(8, 0))
            self.browse_buttons[kind] = button
        self.labels['device'] = ttk.Label(form)
        self.labels['device'].grid(row=4, column=0, columnspan=3, sticky='w', pady=(10, 2))
        self.device = ttk.Combobox(form, state='disabled')
        self.device.grid(row=5, column=0, columnspan=3, sticky='ew')
        ttk.Progressbar(form, variable=self.percent, maximum=100).grid(row=6, column=0, columnspan=3, sticky='ew', pady=(14, 4))
        self.status_label = ttk.Label(form, wraplength=515)
        self.status_label.grid(row=7, column=0, columnspan=3, sticky='w')
        self.eta_label = ttk.Label(form)
        self.eta_label.grid(row=8, column=0, columnspan=3, sticky='w', pady=(2, 8))
        actions = ttk.Frame(form)
        actions.grid(row=9, column=0, columnspan=3, sticky='ew')
        self.labels['start'] = ttk.Button(actions, command=self.start, state='disabled')
        self.labels['start'].pack(side='left')
        self.labels['cancel'] = ttk.Button(actions, command=self.cancel, state='disabled')
        self.labels['cancel'].pack(side='left', padx=6)
        self.console_button = ttk.Button(actions, command=self.toggle_console)
        self.console_button.pack(side='right')
        self.console = ScrolledText(self, height=11, wrap='word', state='disabled', font=('Consolas', 9))
        self.translate()
        self.after(100, self.poll)
        Thread(target=self.detect, daemon=True).start()

    def text(self, key, *args):
        return TEXT[key][self.language.get() == 'Español'].format(*args)

    def translate(self):
        for key, label in self.labels.items():
            label.configure(text=self.text(key))
        for button in self.browse_buttons.values():
            button.configure(text=self.text('browse'))
        self.console_button.configure(text=self.text('hide' if self.console_visible else 'show'))
        self.refresh_status()
        if self.console_visible:
            self.refresh_console()

    def detect(self):
        try:
            self.events.put(('devices', available_devices()))
        except Exception:
            self.events.put(('devices', ([], [traceback.format_exc()])))

    def browse(self, kind):
        types = [('EPUB', '*.epub')] if kind == 'epub' else [
            (self.text('audio_file'), '*.m4b *.m4a *.mp3 *.mp4 *.wav *.flac *.ogg *.opus')]
        path = filedialog.askopenfilename(parent=self, title=self.text(kind), filetypes=[*types, (self.text('files'), '*.*')])
        if path:
            self.paths[kind].set(path)
            self.update_buttons()

    def update_buttons(self):
        can_start = self.devices and all(path.get() for path in self.paths.values()) and not self.running
        self.labels['start'].configure(state='normal' if can_start else 'disabled')
        self.labels['cancel'].configure(state='normal' if self.running else 'disabled')
        self.device.configure(state='readonly' if self.devices and not self.running else 'disabled')
        for button in self.browse_buttons.values():
            button.configure(state='disabled' if self.running else 'normal')

    def start(self):
        index = self.device.current()
        if self.running or index < 0:
            return
        device = self.devices[index]
        epub, audio = (Path(self.paths[k].get()) for k in ('epub', 'audio_file'))
        self.running = True
        self.cancel_event = Event()
        self.transcription_started = self.estimate_end = None
        self.percent.set(0)
        self.status = ('prepare', ())
        self.log('running_on', device.label, device.compute_type)
        self.update_buttons()
        self.refresh_status()
        Thread(target=self.run_sync, args=(epub, audio, device, self.cancel_event), daemon=True).start()

    def run_sync(self, epub, audio, device, cancel_event):
        try:
            output = generate(epub, audio, device=device, cancel_event=cancel_event,
                              progress=lambda *event: self.events.put(('progress', (monotonic(), *event))))
            self.events.put(('finished', output))
        except FileExistsError as error:
            self.events.put(('failed', ('exists', str(error))))
        except Exception:
            self.events.put(('failed', ('error', traceback.format_exc())))

    def cancel(self):
        self.cancel_event.set()
        self.labels['cancel'].configure(state='disabled')
        self.status = ('cancelling', ())
        self.refresh_status()

    def toggle_console(self):
        self.console_visible = not self.console_visible
        if self.console_visible:
            self.console.grid(row=1, column=0, padx=18, pady=(0, 18), sticky='nsew')
            self.refresh_console()
        else:
            self.console.grid_remove()
        self.console_button.configure(text=self.text('hide' if self.console_visible else 'show'))

    def log(self, key, *args):
        self.log_entries.append((datetime.now().strftime('%H:%M:%S'), key, args))
        if self.console_visible:
            self.refresh_console()

    def refresh_console(self):
        content = '\n'.join(f'[{stamp}] {self.text(key, *args) if key else args[0]}'
                            for stamp, key, args in self.log_entries)
        self.console.configure(state='normal')
        self.console.delete('1.0', 'end')
        self.console.insert('1.0', content)
        self.console.see('end')
        self.console.configure(state='disabled')

    def refresh_status(self):
        key, args = self.status
        percentage = f'{self.percent.get():.1f}% · ' if self.running or key in ('done', 'saved') else ''
        self.status_label.configure(text=percentage + self.text(key, *args))
        if self.estimate_end is not None and self.running and key != 'cancelling':
            seconds = max(0, int(self.estimate_end - monotonic()))
            eta = f'{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}'
        else:
            eta = self.text('estimating') if self.running else '—'
        self.eta_label.configure(text=self.text('remaining', eta))

    def handle_progress(self, timestamp, stage, completed, total, *detail):
        if total:
            self.percent.set(100 * completed / total)
        if stage == 'audio':
            if completed == 0:
                self.transcription_started = timestamp
            elif self.transcription_started is not None:
                speed = (timestamp - self.transcription_started) / completed
                self.estimate_end = timestamp + speed * (total - completed)
        key = 'audio_detail' if stage == 'audio' and detail else stage
        self.log(key, *detail)
        if not self.cancel_event.is_set():
            self.status = (key, detail)

    def poll(self):
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == 'devices':
                    self.devices, notes = payload
                    self.device.configure(values=[item.label for item in self.devices])
                    if self.devices:
                        self.update_buttons()
                        self.device.current(next((i for i, item in enumerate(self.devices) if item.kind == 'cuda'), 0))
                    self.status = ('ready' if self.devices else 'no_device', ())
                    for note in notes:
                        self.log(None, note)
                elif event == 'progress':
                    self.handle_progress(*payload)
                else:
                    self.running = False
                    self.estimate_end = None
                    if event == 'failed':
                        key, diagnostic = payload
                        self.status = (key, ())
                        self.log(None, diagnostic)
                        if not self.console_visible:
                            self.toggle_console()
                    elif payload is None:
                        self.status = ('cancelled', ())
                        self.log('cancelled')
                    else:
                        if self.status[0] != 'done':
                            self.status = ('saved', (payload,))
                        self.log('saved', payload)
                    self.update_buttons()
        except Empty:
            pass
        self.refresh_status()
        self.after(150, self.poll)


if __name__ == '__main__':
    Application().mainloop()
