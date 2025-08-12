import streamlit as st
import json
import os
import datetime
import time
import uuid
import subprocess
from pathlib import Path
from gtts import gTTS
from openai import OpenAI
from streamlit_webrtc import webrtc_streamer, WebRtcMode
from aiortc.contrib.media import MediaRecorder

# ========== CONFIG ==========
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
QUESTIONS = [
    "Как ты оцениваешь свой уровень стресса от 1 до 10?",
    "Как ты обычно снимаешь стресс: еда, компьютерные игры?",
]

REC_DIR = Path("recordings")
REC_DIR.mkdir(exist_ok=True)

# ========== SESSION STATE INITIALIZATION ==========
defaults = {
    "start_interview": False,
    "questions_started": False,
    "question_index": 0,
    "question_audio_played": False,
    "answer_start_time": None,
    "timestamps": [],
    "recording_started_at": None,
    "video_ready": False,
    "video_filename": REC_DIR / f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4",
    "transcriptions": [],
    "recorder_stopped": False,
    "processing_started": False,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ========== HELPERS ==========
def text_to_speech(text, filename):
    try:
        tts = gTTS(text=text, lang="ru")
        tts.save(filename)
        return filename
    except Exception as e:
        st.error(f"Ошибка генерации аудио: {e}")
        return None

def whisper_stt(audio_path: Path):
    try:
        with open(audio_path, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ru"
            )
        return transcription.text
    except Exception as e:
        return f"Ошибка распознавания: {str(e)}"

def ffmpeg_available():
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except Exception:
        return False

def cut_audio_segment(video_path: Path, start: float, end: float, output_path: Path):
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-ss", f"{start}",
            "-to", f"{end}",
            "-vn",
            "-acodec", "libmp3lame",
            str(output_path)
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if e.stderr else str(e)
        st.error(f"FFmpeg error while cutting audio: {stderr}")
        return False

# ========== UI ==========
st.title("interview-psychologist")

if not st.session_state.start_interview:
    st.info(
        "📹 Инструкция:\n\n"
        "1. Нажмите **Начать интервью** — это запустит камеру и микрофон и начнёт запись.\n"
        "2. Нажмите **▶ Начать вопросы** — вопросы будут зачитываться вслух.\n"
        "3. После вопроса отвечайте; когда закончите — нажмите **Далее**.\n"
        "4. По окончании, нажмите на красную кнопку «**STOP**» под видео, затем **Получить результаты**.\n"
        "5. Вы получите видео и расшифровку.\n\n"
        "**Важно:** Убедитесь, что ваш браузер разрешил доступ к микрофону и камере."
    )
    if st.button("🎬 Начать интервью"):
        st.session_state.start_interview = True
        st.rerun()
else:
    video_filename_path = str(st.session_state.video_filename)

    # Use 'sendonly' for video and 'sendrecv' for audio to prevent issues
    video_ctx = webrtc_streamer(
    key="interview-video",
    mode=WebRtcMode.SENDRECV,
    media_stream_constraints={
        "video": {"width": 640, "height": 480, "frameRate": 15},
        "audio": True
    },
    # ✅ FIXED: Record the outgoing (looped-back) stream which has audio.
    out_recorder_factory=lambda: MediaRecorder(video_filename_path, format="mp4"),
    )

    if video_ctx.state.playing and st.session_state.recording_started_at is None:
        st.session_state.recording_started_at = time.time()
        st.success("Запись видео началась.")

    # Show "Start Questions" button only when video is playing
    if video_ctx.state.playing and not st.session_state.questions_started and not st.session_state.video_ready:
        if st.button("▶ Начать вопросы"):
            st.session_state.questions_started = True
            st.session_state.question_audio_played = False
            st.rerun()

    if st.session_state.questions_started and not st.session_state.video_ready:
        if st.session_state.question_index < len(QUESTIONS):
            q_idx = st.session_state.question_index
            current_question = QUESTIONS[q_idx]
            st.write(f"Вопрос {q_idx + 1}: {current_question}")

            if not st.session_state.question_audio_played:
                tts_file = REC_DIR / f"q_{q_idx}_{uuid.uuid4().hex}.mp3"
                if text_to_speech(current_question, str(tts_file)):
                    with open(tts_file, "rb") as f:
                        st.audio(f.read(), format="audio/mp3", autoplay=True)
                    tts_file.unlink(missing_ok=True)
                st.session_state.answer_start_time = time.time()
                st.session_state.question_audio_played = True

            st.info("Говорите ответ. Нажмите «Далее», когда закончите.")

            if st.button("Далее"):
                abs_start = st.session_state.answer_start_time or time.time()
                abs_end = time.time()
                rel_start = max(0.0, abs_start - st.session_state.recording_started_at)
                rel_end = max(rel_start + 0.1, abs_end - st.session_state.recording_started_at)

                st.session_state.timestamps.append({
                    "index": q_idx,
                    "start": rel_start,
                    "end": rel_end
                })

                st.session_state.question_index += 1
                st.session_state.question_audio_played = False
                st.session_state.answer_start_time = None

                if st.session_state.question_index >= len(QUESTIONS):
                    st.session_state.video_ready = True

                st.rerun()
        else:
            st.session_state.video_ready = True
            st.rerun()

    # Processing after all questions are done and video is ready to be stopped
    if st.session_state.video_ready and not st.session_state.processing_started:
        st.success("Интервью завершено. Пожалуйста, нажмите на красную кнопку **STOP** под видео, чтобы остановить запись и получить результаты.")
        
        if st.button("Получить результаты"):
            # Check if the user has manually stopped the recording
            if not video_ctx.state.playing:
                st.session_state.processing_started = True
                st.rerun()
            else:
                st.warning("Пожалуйста, сначала нажмите на красную кнопку **STOP** под видео.")

    # This block is for processing the results once the user has stopped the recording
    if st.session_state.processing_started:
        st.info("Обрабатываем видео и расшифровываем ответы...")

        if not ffmpeg_available():
            st.error("FFmpeg не найден в системе. Установите его для продолжения.")
        elif not st.session_state.video_filename.exists():
            st.error("Видеофайл не найден.")
        else:
            results = []
            for seg in st.session_state.timestamps:
                q_idx = seg["index"]
                audio_out = REC_DIR / f"answer_q{q_idx}_{uuid.uuid4().hex}.mp3"
                ok = cut_audio_segment(st.session_state.video_filename, seg["start"], seg["end"], audio_out)

                transcription_text = "Ошибка при обработке"
                if ok and audio_out.exists():
                    transcription_text = whisper_stt(audio_out)
                    audio_out.unlink(missing_ok=True)

                results.append({
                    "question": QUESTIONS[q_idx],
                    "start": seg["start"],
                    "end": seg["end"],
                    "transcription": transcription_text
                })

            st.session_state.transcriptions = results

            st.header("Результаты")
            for r in st.session_state.transcriptions:
                st.write(f"**Вопрос:** {r['question']}")
                st.write(f"**Ответ:** {r['transcription']}")
                st.write(f"**Отрезок:** {r['start']:.2f} — {r['end']:.2f} сек.")
                st.divider()

            st.header("Видеозапись")
            try:
                with open(st.session_state.video_filename, "rb") as f:
                    st.video(f.read())
                    f.seek(0)
                    st.download_button(
                        "Скачать видео (MP4)",
                        data=f.read(),
                        file_name=st.session_state.video_filename.name,
                        mime="video/mp4",
                    )
            except FileNotFoundError:
                st.error("Видеофайл не найден. Возможно, произошла ошибка записи.")


            json_data = {
                "date": datetime.datetime.now().isoformat(),
                "video_file": st.session_state.video_filename.name,
                "answers": st.session_state.transcriptions
            }
            json_filename = st.session_state.video_filename.with_suffix(".json")
            
            # Write the dictionary to the file in JSON format
            with open(json_filename, "w", encoding="utf-8") as f:
                json.dump(json_data, f, ensure_ascii=False, indent=2)

            # Show a success message
            st.success(f"Транскрипт сохранён в файл: {json_filename.name}")

            st.download_button(
                "Скачать результаты (JSON)",
                data=json.dumps(json_data, ensure_ascii=False, indent=2),
                file_name=st.session_state.video_filename.with_suffix(".json").name,
                mime="application/json",
            )
            
            if st.button("🔄 Начать заново"):
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                st.rerun()
