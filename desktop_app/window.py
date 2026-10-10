"""Small desktop window with all automation prompts and progress."""
import json
import queue
import re
import subprocess
import sys
import threading
import webbrowser
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox


class App:
    def __init__(self, root):
        self.root = root
        self.process = None
        self.stop_requested = False
        self.events = queue.Queue()
        root.title('Oracle Course Helper')
        root.geometry('840x620')
        root.minsize(650, 500)
        outer = ttk.Frame(root, padding=20)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Oracle Course Helper', font=('Segoe UI', 19, 'bold')).pack(anchor='w')
        ttk.Label(outer, text='Sign in through the browser. Follow instructions here.').pack(anchor='w', pady=(6, 16))
        self.status = tk.StringVar(value='Select Start to open the bot. Your existing command-line bot is separate.')
        ttk.Label(outer, textvariable=self.status, wraplength=760).pack(anchor='w', fill='x')
        self.progress = ttk.Progressbar(outer, maximum=100)
        self.progress.pack(fill='x', pady=14)
        self.detail = tk.StringVar(value='No run started')
        ttk.Label(outer, textvariable=self.detail).pack(anchor='w')
        self.repo_link = ttk.Button(outer, text='Open GitHub repository',
                                   command=lambda: webbrowser.open('https://github.com/Chaitanya-970/oracle-bot'))
        keys = ttk.Frame(outer)
        keys.pack(fill='x', pady=12)
        ttk.Label(keys, text='Groq API key').pack(side='left')
        self.key = ttk.Entry(keys, show='*')
        self.key.pack(side='left', fill='x', expand=True, padx=10)
        self.use_key = ttk.Button(keys, text='Use key', command=self.send_key, state='disabled')
        self.use_key.pack(side='left')
        buttons = ttk.Frame(outer)
        buttons.pack(fill='x', pady=(0, 12))
        self.start = ttk.Button(buttons, text='Start', command=self.start_worker)
        self.start.pack(side='left')
        self.continue_button = ttk.Button(buttons, text='Continue', command=lambda: self.send({'action':'continue'}), state='disabled')
        self.continue_button.pack(side='left', padx=8)
        self.stop = ttk.Button(buttons, text='Stop', command=self.stop_worker, state='disabled')
        self.stop.pack(side='left')
        ttk.Label(outer, text='The progress bar shows the current assessment, not the percentage of all courses.').pack(anchor='w', pady=(8, 0))
        log_frame = self.log_frame = ttk.Frame(outer)
        log_frame.pack(fill='both', expand=True)
        self.log = tk.Text(log_frame, wrap='word', state='disabled', font=('Consolas', 10))
        scrollbar = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        self.log.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.poll)

    def append(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', text + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def start_worker(self):
        if self.process and self.process.poll() is None:
            return
        self.repo_link.pack_forget()
        command = [sys.executable, '--worker'] if getattr(sys, 'frozen', False) else [sys.executable, '-u', str(Path(__file__).with_name('launch.py')), '--worker']
        try:
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', bufsize=1, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        except OSError as exc:
            self.status.set('The bot process could not start. See the error below.')
            self.append(str(exc))
            return
        self.stop_requested = False
        self.start.configure(state='disabled')
        self.stop.configure(state='normal')
        def read():
            for line in self.process.stdout:
                try:
                    self.events.put(json.loads(line))
                except ValueError:
                    self.events.put({'type':'log', 'level':'ERROR', 'text':re.sub(r'gsk_[A-Za-z0-9]+', '[API key hidden]', line.strip())})
            self.events.put({'type':'exit', 'code':self.process.wait()})
        threading.Thread(target=read, daemon=True).start()

    def send(self, command):
        if self.process and self.process.poll() is None:
            try:
                self.process.stdin.write(json.dumps(command) + '\n')
                self.process.stdin.flush()
                self.continue_button.configure(state='disabled')
            except (BrokenPipeError, OSError):
                self.append('The bot process has stopped. Select Start to reopen it.')

    def send_key(self):
        key = self.key.get().strip()
        if not key:
            messagebox.showinfo('API key needed', 'Enter your Groq API key first.')
            return
        self.send({'action':'key', 'key':key})
        self.key.delete(0, 'end')
        self.status.set('Verifying the API key...')

    def stop_worker(self):
        self.stop_requested = True
        self.send({'action':'stop'})
        self.status.set('Stopping... If a network request is active, it may take a moment.')
        # A pending HTTP wait can outlive the owner thread. Bound shutdown of
        # this dedicated process; the original bot uses a different profile.
        self.root.after(5000, self.force_stop)

    def force_stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()

    def poll(self):
        while not self.events.empty():
            event = self.events.get()
            if event.get('type') == 'log':
                self.append(event.get('level', 'INFO') + ': ' + event.get('text', ''))
                text = event.get('text', '')
                if 'Groq answered in' in text and ('Rate limited' in self.status.get() or
                                                   self.status.get() == 'Verifying the API key...'):
                    self.status.set('Working through your enrolled courses. Progress appears below.')
                match = re.search(r'Question (\d+) of (\d+)', text)
                if match:
                    current, total = map(int, match.groups())
                    self.progress['value'] = current / total * 100
                    self.detail.set(f'Assessment question {current} of {total}')
                elif 'Opening section' in text or 'Opening course' in text:
                    self.detail.set(text)
                    self.progress['value'] = 0
                if event.get('level') == 'WARNING' and 'Rate limited' in text:
                    self.status.set(text)
            elif event.get('type') == 'state':
                self.status.set(event['text'])
                self.append(event['text'])
                state = event['state']
                self.use_key.configure(state='normal' if state in ('key','running','paused') else 'disabled')
                self.continue_button.configure(state='normal' if state in ('login','paused') else 'disabled')
                if state == 'complete':
                    self.progress['value'] = 100
                    self.detail.set('Finished. Congratulations! Please check your final scores in Oracle.')
                    self.repo_link.pack(before=self.log_frame, anchor='w', pady=(6, 0))
                elif state in ('error','stopped'):
                    self.progress['value'] = 0
            elif event.get('type') == 'exit':
                self.start.configure(state='normal')
                self.stop.configure(state='disabled')
                self.use_key.configure(state='disabled')
                self.continue_button.configure(state='disabled')
                self.append('Bot process closed. Exit code: ' + str(event['code']))
                if self.stop_requested:
                    self.status.set('Stopped. Select Start to open the bot again.')
        self.root.after(100, self.poll)

    def close(self):
        if self.process and self.process.poll() is None:
            if not messagebox.askyesno('Close app', 'Stop this desktop run and close the app? Saved Oracle progress will remain.'):
                return
            self.process.terminate()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()
