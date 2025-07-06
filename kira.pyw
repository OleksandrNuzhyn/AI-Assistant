import os
import time
import numpy as np
import sounddevice as sd
from scipy.io.wavfile import write
from PIL import ImageGrab
from openwakeword.model import Model
from openwakeword.utils import download_models
from google.cloud import texttospeech
import threading
from faster_whisper import WhisperModel
from google import genai
from google.genai import types
from dotenv import load_dotenv
import pedalboard as pb
import webview
import win32api
import ctypes

load_dotenv()

WAKEWORD_KIRA_PATH = "wakeword_models/listen_kira.onnx"
WAKEWORD_LIGHT_PATH = "wakeword_models/listen_light.onnx"
WAKEWORD_SILENCE_PATH = "wakeword_models/silence_kira.onnx"

MODEL_GEMINI = "gemini-2.5-flash"
WHISPER_MODEL_SIZE = "Systran/faster-whisper-large-v3"
STT_SAMPLE_RATE = 16000
OWW_SAMPLE_RATE = 16000
OWW_FRAME_LENGTH = 1280
TEMP_AUDIO_FILE = "temp_voice.wav"
COOLDOWN_AFTER_SPEAK = 1.5
IDLE_HIDE_DELAY = 2.5
PID_FILE = "assistant.pid"
SYSTEM_PROMPT = """Ти - мій персональний асистент, аналог Джарвіса. 
Завжди звертайся до мене як 'Сер' лише один раз на початку тексту і в тому ж реченні продовжуй писати текст. 
Надавай відповіді виключно по суті. ВАЖЛИВЕ ПРАВИЛО: уникай сильно великих речень, кожне завершуй крапкою. 
І не роби ніколи жодних переносів в реченні і ніколи не роби перенос речення в інший рядок (всі речення пиши підряд). Також уникай будь-яких символів дужок. 
Відповіді мають бути чистим текстом без жодного форматування: без маркдауну, зірочок, переносів рядків. 
ЗАБОРОНЕНО використовувати англійські літери. Будь-які англійські слова, терміни, імена чи назви технологій пиши виключно українськими літерами, 
передаючи їх фонетичне звучання (наприклад, 'Пайтон', 'Гугл Клауд') (приділяй фонетичному звучанні під час написання великої уваги). 
Враховуй мої дані: я - Олександр, 19-річний програміст з Київської області. 
Мій стек: Пайтон (Джанго, Джанго Рест, Тензорфлоу), ДжаваСкріпт (Вью джіес), Гугл Клауд. 
Я працюю на Віндовс. Надавай лише перевірену інформацію."""

def list_mme_audio_devices():
    hostapis = sd.query_hostapis()
    mme_index = next((i for i, api in enumerate(hostapis) if 'mme' in api['name'].lower()), None)
    if mme_index is None:
        raise RuntimeError("MME host API не знайдено")
    
    devices = sd.query_devices()
    input_indices = [i for i, d in enumerate(devices) if d['hostapi'] == mme_index and d['max_input_channels'] > 0]
    output_indices = [i for i, d in enumerate(devices) if d['hostapi'] == mme_index and d['max_output_channels'] > 0]

    if not input_indices or not output_indices:
        raise RuntimeError("Жодних MME input/output приладів не знайдено")
    
    return input_indices, output_indices

mme_inputs, mme_outputs = list_mme_audio_devices()
devices = sd.query_devices()

print("Доступні MME-входи:")
for idx in mme_inputs:
    print(f"{idx}: {devices[idx]['name']}")

print("\nДоступні MME-виходи:")
for i, idx in enumerate(mme_outputs):
    print(f"{i}: {devices[idx]['name']}")

INPUT_AUDIO_DEVICE = mme_inputs[1]
OUTPUT_AUDIO_DEVICE = mme_outputs[2]

INPUT_AUDIO_DEVICE = "Microphone (2- MR590), MME"
OUTPUT_AUDIO_DEVICE = "Speakers (2- MR590), MME"

class AssistantApp:
    def __init__(self):
        self.window = None
        self.is_recording = False
        self.audio_frames = []
        self.stop_recording_event = threading.Event()
        self.abort_event = threading.Event()
        self.processing_lock = threading.Lock()
        self.owwModel = None
        self.client = None
        self.chat = None
        
    def set_window(self, window):
        self.window = window

    def abort_current_task(self):
        print("Сигнал скасування отримано")
        self.abort_event.set()
        self.stop_recording_event.set()
        sd.stop()

        if self.is_recording:
            self.update_status("Скасовано", 'idle')
            self.is_recording = False
        elif self.processing_lock.locked():
            self.update_status("Зачекайте завершення...", 'processing')
        else:
            self.update_status("Скасовано", 'idle')

    def start_background_tasks(self):
        init_thread = threading.Thread(target=self.init_models_thread, daemon=True)
        init_thread.start()

    def init_models_thread(self):
        self.update_status("Завантаження...", 'processing')

        try:
            download_models()
            self.client = genai.Client()
            self.chat = self.client.chats.create(
                model=MODEL_GEMINI,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    tools=[types.Tool(google_search=types.GoogleSearch())]
                )
            )

            self.stt_model = WhisperModel(WHISPER_MODEL_SIZE, device="auto", compute_type="int8")
            self.tts_client = texttospeech.TextToSpeechClient()
            
            self.owwModel = Model(
                wakeword_models=[WAKEWORD_KIRA_PATH, WAKEWORD_LIGHT_PATH, WAKEWORD_SILENCE_PATH],
                inference_framework='onnx'
            )
            
            listener_thread = threading.Thread(target=self.start_keyword_listener, daemon=True)
            listener_thread.start()

        except Exception as e:
            error_msg = f"Помилка: {str(e)[:100]}"
            self.update_status(error_msg, 'idle')
            print(f"Помилка ініціалізації: {e}")
            return

        self.update_status("Готовий до роботи", 'idle')

    def update_status(self, text, state):
        if not self.window:
            return
        try:
            text_js = text.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')
            js = f'window.updateStatus("{text_js}", "{state}")'
            if hasattr(self.window, 'evaluate_js'):
                self.window.evaluate_js(js)
            elif hasattr(self.window, 'page'):
                self.window.page().runJavaScript(js)

            self.window.show()
            if state == 'idle':
                threading.Timer(IDLE_HIDE_DELAY, self.window.hide).start()
        except Exception as e:
            print(f"Помилка оновлення UI: {e}")

    def start_keyword_listener(self):
        try:
            model_kira_name = os.path.basename(WAKEWORD_KIRA_PATH).split('.')[0]
            model_light_name = os.path.basename(WAKEWORD_LIGHT_PATH).split('.')[0]
            model_silence_name = os.path.basename(WAKEWORD_SILENCE_PATH).split('.')[0]

            with sd.InputStream(samplerate=OWW_SAMPLE_RATE, channels=1, dtype='int16', blocksize=OWW_FRAME_LENGTH, device=INPUT_AUDIO_DEVICE) as stream:
                print("Слухаю ключові слова з OpenWakeWord...")
                while True:
                    pcm, _ = stream.read(OWW_FRAME_LENGTH)
                    pcm = pcm.flatten()
                    
                    if self.is_recording:
                        prediction = self.owwModel.predict(pcm, threshold={model_silence_name: 0.5}, debounce_time=1)
                        if prediction[model_silence_name] > 0.5:
                            if self.is_recording:
                                self.stop_recording_event.set()
                    else:
                        if not self.processing_lock.locked():
                            prediction = self.owwModel.predict(pcm, threshold={model_kira_name: 0.5, model_light_name: 0.5}, debounce_time=1)
                            
                            if prediction[model_kira_name] > 0.5:
                                self.abort_event.clear()
                                self.stop_recording_event.clear()
                                processing_thread = threading.Thread(target=self.process_query_thread, args=(False,), daemon=True)
                                processing_thread.start()
                            elif prediction[model_light_name] > 0.5:
                                self.abort_event.clear()
                                self.stop_recording_event.clear()
                                processing_thread = threading.Thread(target=self.process_query_thread, args=(True,), daemon=True)
                                processing_thread.start()

        except Exception as e:
            print(f"Критична помилка в слухачі OpenWakeWord: {e}")
            self.update_status("Помилка OpenWakeWord", 'idle')
    
    def process_query_thread(self, with_screenshot):
        with self.processing_lock:
            self.is_recording = True
            screenshot_image = None
            
            if with_screenshot:
                screenshot_image = ImageGrab.grab()
                self.update_status("Деталізований запис...", 'listening')
            else:
                self.update_status("Запис...", 'listening')

            self.audio_frames = []
            try:
                with sd.InputStream(samplerate=STT_SAMPLE_RATE, channels=1, dtype='int16', device=INPUT_AUDIO_DEVICE) as stream:
                    while not self.stop_recording_event.is_set():
                        if self.abort_event.is_set():
                            break
                        audio_chunk, _ = stream.read(1024)
                        self.audio_frames.append(audio_chunk)
            except Exception as e:
                 print(f"Помилка запису аудіо: {e}")
                 self.update_status("Помилка запису", 'idle')
                 self.is_recording = False
                 return

            if self.abort_event.is_set():
                self.is_recording = False
                self.update_status("Готовий до роботи", 'idle')
                return

            self.is_recording = False
            self.update_status("Обробка...", 'processing')

            if not self.audio_frames or len(self.audio_frames) < 6:
                self.update_status("Запис надто короткий", 'idle')
                time.sleep(2)
                self.update_status("Готовий до роботи", 'idle')
                return

            audio_data = np.concatenate(self.audio_frames, axis=0)
            
            samples_to_trim = STT_SAMPLE_RATE
            if len(audio_data) > samples_to_trim:
                audio_data = audio_data[:-samples_to_trim]

            write(TEMP_AUDIO_FILE, STT_SAMPLE_RATE, audio_data)
            
            self.update_status("Розпізнавання...", 'processing')
            segments, _ = self.stt_model.transcribe(TEMP_AUDIO_FILE, beam_size=5, language="uk")
            if self.abort_event.is_set():
                self.update_status("Готовий до роботи", 'idle')
                return

            user_text = " ".join([segment.text for segment in segments]).strip()
            os.remove(TEMP_AUDIO_FILE)
            
            if not user_text:
                self.update_status("Нічого не розпізнано", 'idle')
                time.sleep(2)
                self.update_status("Готовий до роботи", 'idle')
                return
                
            print(f"\n[You]: {user_text}")

            if self.abort_event.is_set():
                self.update_status("Готовий до роботи", 'idle')
                return

            try:
                self.update_status("Формую відповідь...", 'processing')
                if screenshot_image:
                    response = self.chat.send_message([screenshot_image, user_text])
                else:
                    response = self.chat.send_message(user_text)
                    
                response_text = response.text
                print(f"[AI]: {response_text}")
            except Exception as e:
                response_text = f"Вибачте, сталася помилка API. {e}"
                print(f"[Error]: {response_text}")

            if self.abort_event.is_set():
                self.update_status("Готовий до роботи", 'idle')
                return

            self.speak_google_cloud(response_text)
            time.sleep(COOLDOWN_AFTER_SPEAK)

    def speak_google_cloud(self, text):
        if not text or self.abort_event.is_set():
            return
        
        try:
            self.update_status("Синтез мовлення...", 'processing')
            synthesis_input = texttospeech.SynthesisInput(text=text)
            voice = texttospeech.VoiceSelectionParams(language_code="uk-UA", name="uk-UA-Chirp3-HD-Enceladus")
            audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.LINEAR16, speaking_rate=1.05, sample_rate_hertz=24000)

            response = self.tts_client.synthesize_speech(input=synthesis_input, voice=voice, audio_config=audio_config)

            audio_data = np.frombuffer(response.audio_content, dtype=np.int16).astype(np.float32) / 32767.0
            
            self.update_status("Обробка аудіо...", 'processing')
            playback_sample_rate = 24000

            board = pb.Pedalboard([
                pb.HighpassFilter(cutoff_frequency_hz=80),
                pb.Compressor(threshold_db=-16, ratio=3.0, attack_ms=5, release_ms=150),
                pb.LowShelfFilter(cutoff_frequency_hz=200, gain_db=0.5, q=0.7),
                pb.PeakFilter(cutoff_frequency_hz=3500, gain_db=0.5, q=1.0),
                pb.Reverb(room_size=0.15, wet_level=0.04, dry_level=0.96, width=0.5),
                pb.Gain(gain_db=-5.0)
            ])

            processed_audio = board(audio_data, playback_sample_rate)
            processed_audio_int16 = (processed_audio * 32767.0).astype(np.int16).flatten()

            fade_in_duration_ms = 40
            fade_in_samples = int(fade_in_duration_ms / 1000 * playback_sample_rate)
            if len(processed_audio_int16) > fade_in_samples:
                fade_curve = np.power(np.linspace(0.0, 1.0, fade_in_samples), 2)
                processed_audio_int16[:fade_in_samples] = (processed_audio_int16[:fade_in_samples].astype(np.float32) * fade_curve).astype(np.int16)
            
            self.update_status("Говорю...", 'speaking')
            sd.play(processed_audio_int16, playback_sample_rate, device=OUTPUT_AUDIO_DEVICE)
            while sd.get_stream().active:
                if self.abort_event.is_set():
                    sd.stop()
                    break
                time.sleep(0.1)

        except Exception as e:
            print(f"Помилка синтезу мовлення: {e}")
        
        self.update_status("Готовий до роботи", 'idle')

    def shutdown(self, *args):
        print("\nЗавершення роботи...")
        if self.window:
            self.window.destroy()

def show_modal_web(app_logic):
    mi = win32api.GetMonitorInfo(win32api.MonitorFromPoint((0,0)))
    screen_width, screen_height = mi.get("Monitor")[2], mi.get("Monitor")[3]

    width = 380
    height = 26
    margin_bottom = 74
    x = (screen_width - width) // 2
    y = screen_height - height - margin_bottom

    html_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "web", "index.html"))

    window = webview.create_window(
        "Assistant",
        url=f"file://{html_path}",
        x=x, y=y,
        width=width, height=height,
        resizable=False, frameless=True, on_top=True,
        min_size=(width, height),
        background_color='#1a1a1a'
    )
    app_logic.set_window(window)

    window.expose(app_logic.abort_current_task)

    def apply_window_style():
        try:
            hwnd = ctypes.windll.user32.FindWindowW(None, "Assistant")
            if hwnd:
                GWL_EXSTYLE = -20
                WS_EX_TOOLWINDOW = 0x00000080
                WS_EX_APPWINDOW = 0x00040000
                ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                ex_style = (ex_style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style)
                SWP_NOSIZE, SWP_NOMOVE = 0x0001, 0x0002
                HWND_TOPMOST = -1
                ctypes.windll.user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
                ctypes.windll.user32.BringWindowToTop(hwnd)
                ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception as e:
            print(f"Помилка створення стилю вікна: {e}")

    window.events.loaded += apply_window_style
    window.events.loaded += lambda: app_logic.start_background_tasks()

    webview.start(gui='edgechromium')

def main():
    app_logic = AssistantApp()
    show_modal_web(app_logic)

if __name__ == "__main__":
    main()
