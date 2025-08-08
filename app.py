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

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Sample questions
QUESTIONS = [
    "Tell me about yourself.",
    "What are your strengths?",
    "Describe a challenging project you worked on.",
    "Why do you want this position?",
    "Where do you see yourself in five years?"
]

# Session state initialization
if "question_index" not in st.session_state:
    st.session_state.question_index = 0
if "transcriptions" not in st.session_state:
    st.session_state.transcriptions = []
if "video_path" not in st.session_state:
    st.session_state.video_path = None

# Directory for recordings
REC_DIR = Path("recordings")
REC_DIR.mkdir(exist_ok=True)

if "rec_filename" not in st.session_state:
    prefix = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    st.session_state.rec_filename = REC_DIR / f"{prefix}.mp4"

out_path = st.session_state.rec_filename

# Text-to-speech
def text_to_speech(text, filename):
    try:
        tts = gTTS(text=text, lang="en")
        tts.save(filename)
        return filename
    except Exception as e:
        st.error(f"Error generating audio: {e}")
        return None

# Whisper STT with streamlit-mic-recorder
def whisper_stt(question_index):
    audio = mic_recorder(
        start_prompt="🎙️ Speak your answer",
        stop_prompt="⏹️ Stop",
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
                language="en"
            )
            return transcription.text
        except Exception as e:
            st.error(f"Transcription failed: {e}")
            return "Transcription failed"
    return None

# Recorder factory for both video + audio
def in_recorder_factory():
    return MediaRecorder(str(out_path), format="mp4")

# UI
st.title("Interview Practice App")

ctx = webrtc_streamer(
    key="interview-recorder",
    mode=WebRtcMode.SENDRECV,
    media_stream_constraints={"video": True, "audio": True},
    in_recorder_factory=in_recorder_factory,
)

# Ask questions
if st.session_state.question_index < len(QUESTIONS):
    current_question = QUESTIONS[st.session_state.question_index]
    st.write(f"Question {st.session_state.question_index + 1}: {current_question}")

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
        st.rerun()

# Interview completed
if st.session_state.question_index >= len(QUESTIONS) and ctx and not ctx.state.playing:
    if out_path.exists() and out_path.stat().st_size > 100_000:
        st.subheader("Interview completed!")
        for item in st.session_state.transcriptions:
            st.write(f"**Question:** {item['question']}")
            st.write(f"**Your Answer:** {item['transcription']}")
            st.write(f"**Timestamp:** {item['timestamp']}")
            st.write("---")

        st.subheader("Video Recording with Audio")
        st.video(str(out_path))
        st.download_button(
            "Download Video",
            data=out_path.read_bytes(),
            file_name=out_path.name,
            mime="video/mp4",
        )

        results = {
            "interview_date": datetime.datetime.now().isoformat(),
            "questions": st.session_state.transcriptions
        }
        json_filename = f"interview_results_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(json_filename, "w") as f:
            json.dump(results, f, indent=2)

        with open(json_filename, "rb") as f:
            st.download_button("Download Results (JSON)", f, json_filename, "application/json")

        if st.button("Start New Interview"):
            st.session_state.question_index = 0
            st.session_state.transcriptions = []
            st.session_state.video_path = None
            st.session_state.rec_filename = REC_DIR / f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
            st.rerun()
