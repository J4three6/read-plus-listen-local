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
from engine import generate, output_path
from media import ffprobe
from pairing import pairs_for


TEXT = {
    'subtitle': ('Align an entire audiobook with its EPUB.', 'Alinea el audiolibro completo con su EPUB.'),
    'language': ('Language', 'Idioma'),
    'epub': ('EPUB files', 'Archivos EPUB'),
    'audio_file': ('Audio files', 'Archivos de audio'),
    'browse': ('Add files…', 'Añadir archivos…'),
    'remove': ('Remove selected book', 'Quitar libro seleccionado'),
    'estimate': ('Estimated left', 'Restante estimado'),
    'elapsed': ('Elapsed', 'Tiempo real'),
    'remaining_total': ('Total estimated time left  {0}', 'Tiempo restante total estimado  {0}'),
    'device': ('Processing device (CPU or GPU)', 'Dispositivo de procesamiento (CPU o GPU)'),
    'detect': ('Detecting devices…', 'Detectando dispositivos…'),
    'no_device': ('No usable CPU or GPU detected. Open the console for details.',
                  'No se detectó una CPU o GPU utilizable. Abre la consola para ver los detalles.'),
    'start': ('Synchronize', 'Sincronizar'),
    'cancel': ('Cancel', 'Cancelar'),
    'show': ('Show console', 'Mostrar consola'),
    'hide': ('Hide console', 'Ocultar consola'),
    'ready': ('Select EPUB and audio files, then choose a device.',
              'Selecciona archivos EPUB y de audio, y elige un dispositivo.'),
    'selected_files': ('{0} files selected', '{0} archivos seleccionados'),
    'queue': ('{0} books ready · {1} files unpaired', '{0} libros listos · {1} archivos sin pareja'),
    'no_pairs': ('No clear matches. Select the files for one book to pair them manually.',
                 'No hay coincidencias claras. Selecciona los archivos de un solo libro para emparejarlos manualmente.'),
    'pair': ('{0} → {1}', '{0} → {1}'),
    'unpaired': ('Unpaired: {0}', 'Sin pareja: {0}'),
    'book': ('Book {0}/{1} · {2}', 'Libro {0}/{1} · {2}'),
    'book_done': ('{0} · finished in {1}', '{0} · completado en {1}'),
    'book_failed': ('{0} · failed after {1}', '{0} · falló después de {1}'),
    'book_skipped': ('{0} · skipped in {1} because a JSON already exists',
                     '{0} · omitido en {1} porque ya existe un JSON'),
    'book_cancelled': ('{0} · cancelled after {1}', '{0} · cancelado después de {1}'),
    'batch_done': ('Queue finished · {0} completed, {1} skipped, {2} failed · {3}',
                   'Cola finalizada · {0} completados, {1} omitidos, {2} con error · {3}'),
    'prepare': ('Reading the EPUB and audio metadata…', 'Leyendo los metadatos del EPUB y el audio…'),
    'model': ('Loading Whisper base…', 'Cargando Whisper base…'),
    'audio': ('Transcribing the audiobook…', 'Transcribiendo el audiolibro…'),
    'audio_detail': ('Audio: {0}/{1} s · {2} words recognized', 'Audio: {0}/{1} s · {2} palabras reconocidas'),
    'align': ('Aligning the full transcript with the EPUB…', 'Alineando la transcripción completa con el EPUB…'),
    'finalizing': ('Finishing...', 'Finalizando...'),
    'save': ('Saving the synchronization JSON…', 'Guardando el JSON de sincronización…'),
    'done': ('Finished · {0:,} of {1:,} EPUB words aligned', 'Terminado · {0:,} de {1:,} palabras del EPUB alineadas'),
    'saved': ('Saved to {0}', 'Guardado en {0}'),
    'cancelling': ('Cancelling…', 'Cancelando…'),
    'cancelled': ('Cancelled.', 'Cancelado.'),
    'error': ('Synchronization failed. See the console for details.', 'Falló la sincronización. Consulta la consola.'),
    'exists': ('An export already exists. Rename it to run again.', 'Ya existe una exportación. Renómbrala para repetir el proceso.'),
    'estimating': ('Estimating…', 'Calculando…'),
    'files': ('All files', 'Todos los archivos'),
    'running_on': ('Processing on {0} ({1})', 'Procesando en {0} ({1})'),
}


def clock(elapsed):
    seconds = max(0, int(elapsed))
    return f'{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}'


class Application(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Read & Listen — Sync Engine 3')
        self.minsize(720, 490)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        system_language = locale.getlocale()[0] or ''
        self.language = tk.StringVar(value='Español' if system_language.lower().startswith(('es', 'spanish')) else 'English')
        self.paths = {kind: () for kind in ('epub', 'audio_file')}
        self.path_labels = {kind: tk.StringVar() for kind in self.paths}
        self.pairs = []
        self.unpaired = []
        self.active_book = None
        self.book_number = self.batch_size = 0
        self.durations = []
        self.book_elapsed = {}
        self.rate = None
        self.sample_time = self.sample_audio = 0.0
        self.audio_started = None
        self.eta_timestamp = None
        self.active_remaining = None
        self.events = Queue()
        self.devices = []
        self.running = False
        self.console_visible = False
        self.log_entries = []
        self.status = ('detect', ())
        self.percent = tk.DoubleVar()
        self.labels = {}

        form = ttk.Frame(self, padding=18)
        form.grid(sticky='nsew')
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
            ttk.Entry(form, textvariable=self.path_labels[kind], state='readonly').grid(row=row, column=1, sticky='ew', pady=4)
            button = ttk.Button(form, command=lambda k=kind: self.browse(k))
            button.grid(row=row, column=2, sticky='w', padx=(8, 0))
            self.browse_buttons[kind] = button
        self.labels['device'] = ttk.Label(form)
        self.labels['device'].grid(row=4, column=0, columnspan=3, sticky='w', pady=(10, 2))
        self.device = ttk.Combobox(form, state='disabled')
        self.device.grid(row=5, column=0, columnspan=3, sticky='ew')
        queue_frame = ttk.Frame(form)
        queue_frame.grid(row=6, column=0, columnspan=3, sticky='nsew', pady=(12, 0))
        queue_frame.columnconfigure(0, weight=1)
        queue_frame.rowconfigure(0, weight=1)
        form.rowconfigure(6, weight=1)
        self.queue_view = ttk.Treeview(queue_frame, columns=('epub', 'audio_file', 'estimate', 'elapsed'),
                                       show='headings', selectmode='browse', height=6)
        for column, width in [('epub', 220), ('audio_file', 220), ('estimate', 115), ('elapsed', 90)]:
            self.queue_view.column(column, width=width, stretch=column in ('epub', 'audio_file'))
        self.queue_view.grid(row=0, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(queue_frame, orient='vertical', command=self.queue_view.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        self.queue_view.configure(yscrollcommand=scrollbar.set)
        self.queue_view.bind('<<TreeviewSelect>>', lambda _: self.update_remove())
        self.labels['remove'] = ttk.Button(queue_frame, command=self.remove_selected, state='disabled')
        self.labels['remove'].grid(row=1, column=0, sticky='e', pady=(4, 0))
        ttk.Progressbar(form, variable=self.percent, maximum=100).grid(row=7, column=0, columnspan=3, sticky='ew', pady=(12, 4))
        self.status_label = ttk.Label(form, wraplength=515)
        self.status_label.grid(row=8, column=0, columnspan=3, sticky='w')
        self.eta_label = ttk.Label(form)
        self.eta_label.grid(row=9, column=0, columnspan=3, sticky='w', pady=(2, 8))
        actions = ttk.Frame(form)
        actions.grid(row=10, column=0, columnspan=3, sticky='ew')
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
        for column in ('epub', 'audio_file', 'estimate', 'elapsed'):
            self.queue_view.heading(column, text=self.text(column))
        self.update_path_labels()
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
        paths = filedialog.askopenfilenames(parent=self, title=self.text(kind),
                                            filetypes=[*types, (self.text('files'), '*.*')])
        if paths:
            candidates = (*self.paths[kind], *(Path(path).resolve() for path in paths))
            self.paths[kind] = tuple(dict.fromkeys(candidates))
            self.rebuild_queue()

    def rebuild_queue(self):
        self.update_path_labels()
        self.pairs, epubs, audios = pairs_for(self.paths['epub'], self.paths['audio_file'])
        self.unpaired = epubs + audios
        self.durations = []
        self.book_elapsed.clear()
        self.queue_view.delete(*self.queue_view.get_children())
        for index, (epub, audio) in enumerate(self.pairs):
            self.queue_view.insert('', 'end', iid=str(index), values=(epub.name, audio.name, '—', '—'))
        if all(self.paths.values()):
            self.status = ('queue', (len(self.pairs), len(self.unpaired))) if self.pairs else ('no_pairs', ())
            self.log_queue()
            if self.unpaired and not self.console_visible:
                self.toggle_console()
        else:
            self.status = ('ready', ())
        self.percent.set(0)
        self.update_buttons()

    def update_remove(self):
        enabled = not self.running and bool(self.queue_view.selection())
        self.labels['remove'].configure(state='normal' if enabled else 'disabled')

    def remove_selected(self):
        selection = self.queue_view.selection()
        if self.running or not selection:
            return
        epub, audio = self.pairs[int(selection[0])]
        for kind, path in [('epub', epub), ('audio_file', audio)]:
            self.paths[kind] = tuple(item for item in self.paths[kind] if item != path)
        self.rebuild_queue()

    def update_path_labels(self):
        for kind, paths in self.paths.items():
            label = paths[0].name if len(paths) == 1 else self.text('selected_files', len(paths)) if paths else ''
            self.path_labels[kind].set(label)

    def log_queue(self):
        for epub, audio in self.pairs:
            self.log('pair', epub.name, audio.name)
        for path in self.unpaired:
            self.log('unpaired', path.name)

    def update_buttons(self):
        can_start = self.devices and self.pairs and not self.running
        self.labels['start'].configure(state='normal' if can_start else 'disabled')
        self.update_remove()
        self.labels['cancel'].configure(state='normal' if self.running else 'disabled')
        self.device.configure(state='readonly' if self.devices and not self.running else 'disabled')
        for button in self.browse_buttons.values():
            button.configure(state='disabled' if self.running else 'normal')

    def start(self):
        index = self.device.current()
        if self.running or index < 0 or not self.pairs:
            return
        device = self.devices[index]
        self.batch_size = len(self.pairs)
        self.book_number = 0
        self.active_book = None
        self.running = True
        self.cancel_event = Event()
        self.durations = []
        self.book_elapsed.clear()
        self.rate = None
        self.sample_time = self.sample_audio = 0.0
        self.audio_started = self.active_remaining = self.eta_timestamp = None
        self.percent.set(0)
        self.status = ('prepare', ())
        self.log('running_on', device.label, device.compute_type)
        self.log_queue()
        if self.batch_size > 1 and not self.console_visible:
            self.toggle_console()
        self.update_buttons()
        self.refresh_status()
        Thread(target=self.run_batch, args=(tuple(self.pairs), device, self.cancel_event), daemon=True).start()

    def run_batch(self, pairs, device, cancel_event):
        counts = {'book_done': 0, 'book_skipped': 0, 'book_failed': 0}
        started = monotonic()
        durations = []
        for epub, audio in pairs:
            if cancel_event.is_set():
                break
            try:
                duration = 0 if output_path(epub).exists() else float(ffprobe(audio)['format']['duration'])
                durations.append(duration if duration >= 0 and duration < float('inf') else None)
            except (OSError, RuntimeError, ValueError, KeyError, TypeError):
                # Let generate report file-specific diagnostics without stopping the queue.
                durations.append(None)
        self.events.put(('durations', durations))
        for number, (epub, audio) in enumerate(pairs, 1):
            if cancel_event.is_set():
                break
            book_start = monotonic()
            self.events.put(('book', (number, epub.name)))
            output = diagnostic = None
            try:
                output = generate(epub, audio, device=device, cancel_event=cancel_event,
                                  progress=lambda *event: self.events.put(('progress', (monotonic(), *event))))
                outcome = 'book_done' if output is not None else 'book_cancelled'
            except FileExistsError as error:
                outcome, diagnostic = 'book_skipped', str(error)
            except Exception:
                outcome, diagnostic = 'book_failed', traceback.format_exc()
            if outcome in counts:
                counts[outcome] += 1
            self.events.put(('book_result', (outcome, epub.name, clock(monotonic() - book_start),
                                            output, diagnostic)))
        self.events.put(('finished', (cancel_event.is_set(), tuple(counts.values()), clock(monotonic() - started))))

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
        percentage = f'{self.percent.get():.1f}% · ' if self.running or key == 'batch_done' else ''
        book = self.text('book', self.book_number, self.batch_size, self.active_book) + '\n' if self.running and self.active_book else ''
        self.status_label.configure(text=book + percentage + self.text(key, *args))
        estimates = self.refresh_queue_times()
        pending = [value for index, value in enumerate(estimates) if index not in self.book_elapsed]
        if self.running and pending:
            total = clock(sum(pending)) if all(value is not None for value in pending) else self.text('estimating')
        else:
            total = '—'
        self.eta_label.configure(text=self.text('remaining_total', total))

    def refresh_queue_times(self):
        estimates = []
        for index in range(len(self.pairs)):
            elapsed = self.book_elapsed.get(index)
            estimate = None
            finalizing = self.running and elapsed is None and index == self.book_number - 1 and self.rate is not None and self.status[0] in ('align', 'save')
            if finalizing:
                estimate = 0
            elif self.running and elapsed is None and index < len(self.durations):
                duration = self.durations[index]
                if duration == 0:
                    estimate = 0
                elif index == self.book_number - 1 and self.active_remaining is not None:
                    estimate = max(0, self.active_remaining - (monotonic() - self.eta_timestamp))
                elif duration is not None and self.rate is not None:
                    estimate = duration * self.rate
            estimates.append(estimate)
            pending = self.running and elapsed is None
            label = self.text('finalizing') if finalizing else (
                clock(estimate) if estimate is not None else self.text('estimating') if pending else '—'
            )
            row = str(index)
            if self.queue_view.set(row, 'estimate') != label:
                self.queue_view.set(row, 'estimate', label)
            if self.queue_view.set(row, 'elapsed') != (elapsed or '—'):
                self.queue_view.set(row, 'elapsed', elapsed or '—')
        return estimates

    def handle_progress(self, timestamp, stage, completed, total, *detail):
        if total:
            books_done = self.book_number - 1 + completed / total
            self.percent.set(100 * books_done / self.batch_size)
        if stage == 'audio' and not detail:
            self.audio_started = timestamp
        elif stage == 'audio' and detail and self.audio_started is not None:
            processed, duration, _ = detail
            seconds = self.sample_time + timestamp - self.audio_started
            audio = self.sample_audio + processed
            if audio > 0:
                self.rate = seconds / audio
                self.active_remaining = self.rate * max(0, duration - processed)
                self.eta_timestamp = timestamp
                if processed >= duration:
                    self.sample_time, self.sample_audio = seconds, audio
                    self.audio_started = None
        elif stage in ('align', 'save'):
            self.active_remaining = None
            self.eta_timestamp = None
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
                elif event == 'durations':
                    self.durations = payload
                elif event == 'book':
                    self.book_number, self.active_book = payload
                    self.audio_started = self.active_remaining = self.eta_timestamp = None
                    self.status = ('prepare', ()) if not self.cancel_event.is_set() else ('cancelling', ())
                    self.log('book', self.book_number, self.batch_size, self.active_book)
                elif event == 'progress':
                    self.handle_progress(*payload)
                elif event == 'book_result':
                    outcome, name, elapsed, output, diagnostic = payload
                    self.book_elapsed[self.book_number - 1] = elapsed
                    self.log(outcome, name, elapsed)
                    if output:
                        self.log('saved', output)
                    if diagnostic:
                        self.log(None, diagnostic)
                    if outcome != 'book_cancelled':
                        self.percent.set(100 * self.book_number / self.batch_size)
                elif event == 'finished':
                    cancelled, counts, elapsed = payload
                    self.running = False
                    self.status = ('cancelled', ()) if cancelled else ('batch_done', (*counts, elapsed))
                    self.log(*self.status)
                    if not self.console_visible:
                        self.toggle_console()
                    self.update_buttons()
        except Empty:
            pass
        self.refresh_status()
        self.after(150, self.poll)


if __name__ == '__main__':
    Application().mainloop()
