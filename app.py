import streamlit as st
import json
import os
import datetime
import io
from gtts import gTTS
from openai import OpenAI
from streamlit_webrtc import webrtc_streamer, WebRtcMode
from aiortc.contrib.media import MediaRecorder
from pathlib import Path
from streamlit_mic_recorder import mic_recorder
import time

# Инициализация OpenAI клиента
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Вопросы на русском
QUESTIONS = [
    "Расскажите о себе.",
    # "Каковы ваши сильные стороны?",
    # "Опишите сложный проект, над которым вы работали.",
    # "Почему вы хотите получить эту должность?",
    # "Где вы видите себя через пять лет?"
]

# --- Состояния сессии ---
if "start_interview" not in st.session_state:
    st.session_state.start_interview = False
if "recording_started" not in st.session_state:
    st.session_state.recording_started = False
if "question_index" not in st.session_state:
    st.session_state.question_index = 0
if "transcriptions" not in st.session_state:
    st.session_state.transcriptions = []
if "video_ready" not in st.session_state:
    st.session_state.video_ready = False

# Директория для записей
REC_DIR = Path("recordings")
REC_DIR.mkdir(exist_ok=True)

if "rec_filename" not in st.session_state:
    prefix = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    st.session_state.rec_filename = REC_DIR / f"{prefix}.mp4"

out_path = st.session_state.rec_filename

# --- Текст в речь ---
def text_to_speech(text, filename):
    try:
        tts = gTTS(text=text, lang="ru")
        tts.save(filename)
        return filename
    except Exception as e:
        st.error(f"Ошибка генерации аудио: {e}")
        return None

# --- Распознавание речи Whisper ---
def whisper_stt(question_index):
    audio = mic_recorder(
        start_prompt="🎙️ Говорите свой ответ",
        stop_prompt="⏹️ Стоп",
        format="webm",
        key=f"whisper_{question_index}"
    )
    if audio:
        audio_bio = io.BytesIO(audio["bytes"])
        audio_bio.name = "audio.webm"
        try:
            transcription = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_bio,
                language="ru"
            )
            return transcription.text
        except Exception as e:
            st.error(f"Ошибка распознавания: {e}")
            return "Ошибка распознавания"
    return None

# --- Фабрика записи видео+аудио ---
def in_recorder_factory():
    return MediaRecorder(str(out_path), format="mp4")

# --- Заголовок ---
st.title("Тренажёр собеседований")

# --- Этап 1: Начало интервью ---
if not st.session_state.start_interview:
    st.info(
    "📹 Это тренажёр собеседований.\n\n"
    "1️⃣ Нажмите **«🎬 Начать интервью»**, чтобы запустить камеру и микрофон.\n"
    "2️⃣ Убедитесь, что видео и звук работают, нажмите **«START»**\n"
    "3️⃣ Когда будете готовы — нажмите **«▶ Начать вопросы»**, и каждый вопрос будет задаваться вслух.\n"
    "4️⃣ После каждого вопроса говорите свой ответ в микрофон.\n"
    "5️⃣ По завершении вы сможете скачать видео и текстовую расшифровку."
)

    if st.button("🎬 Начать интервью"):
        st.session_state.start_interview = True
        st.rerun()
else:
    # --- Этап 2: Запуск WebRTC записи ---
    ctx = webrtc_streamer(
        key="interview-recorder",
        mode=WebRtcMode.SENDRECV,
        media_stream_constraints={"video": True, "audio": True},
        in_recorder_factory=in_recorder_factory,
    )

    # --- Этап 3: Ожидание подтверждения начала вопросов ---
    if ctx.state.playing and not st.session_state.recording_started:
        st.success("Запись видео началась! Когда будете готовы — нажмите кнопку для начала вопросов.")
        if st.button("▶ Начать вопросы"):
            st.session_state.recording_started = True
            st.rerun()

    # --- Этап 4: Процесс интервью ---
    if st.session_state.recording_started and not st.session_state.video_ready:
        if st.session_state.question_index < len(QUESTIONS):
            current_question = QUESTIONS[st.session_state.question_index]
            st.write(f"Вопрос {st.session_state.question_index + 1}: {current_question}")

            audio_file = f"question_{st.session_state.question_index}.mp3"
            if text_to_speech(current_question, audio_file):
                with open(audio_file, "rb") as f:
                    st.audio(f.read(), format="audio/mp3", autoplay=True)

            transcription = whisper_stt(st.session_state.question_index)
            if transcription:
                st.session_state.transcriptions.append({
                    "question": current_question,
                    "transcription": transcription,
                    "timestamp": datetime.datetime.now().isoformat()
                })

                st.session_state.question_index += 1
                if os.path.exists(audio_file):
                    os.remove(audio_file)

                # Если это был последний вопрос → завершаем интервью
                if st.session_state.question_index >= len(QUESTIONS):
                    st.session_state.recording_started = False
                    # Ждём, пока файл записи станет достаточно большим (запись завершится)
                    for _ in range(15):
                        if out_path.exists() and out_path.stat().st_size > 100_000:
                            st.session_state.video_ready = True
                            break
                        time.sleep(0.3)
                    st.rerun()
                else:
                    st.rerun()

    # --- Этап 5: Завершение интервью ---
    if st.session_state.video_ready:
        st.subheader("Интервью завершено!")
        for item in st.session_state.transcriptions:
            st.write(f"**Вопрос:** {item['question']}")
            st.write(f"**Ваш ответ:** {item['transcription']}")
            st.write(f"**Время:** {item['timestamp']}")
            st.write("---")

        st.subheader("Видеозапись с аудио")
        st.video(str(out_path))
        st.download_button(
            "Скачать видео (MP4)",
            data=out_path.read_bytes(),
            file_name=out_path.name,
            mime="video/mp4",
        )

        results = {
            "дата_интервью": datetime.datetime.now().isoformat(),
            "вопросы": st.session_state.transcriptions
        }
        json_filename = f"результаты_интервью_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(json_filename, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        with open(json_filename, "rb") as f:
            st.download_button("Скачать результаты (JSON)", f, json_filename, "application/json")

        if st.button("🔄 Начать новое интервью"):
            st.session_state.start_interview = False
            st.session_state.recording_started = False
            st.session_state.question_index = 0
            st.session_state.transcriptions = []
            st.session_state.video_ready = False
            st.session_state.rec_filename = REC_DIR / f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
            st.rerun()
