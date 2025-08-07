import streamlit as st
import json
import os
import datetime
import io
from gtts import gTTS
from openai import OpenAI
from streamlit_webrtc import webrtc_streamer, VideoProcessorBase, RTCConfiguration
from streamlit_mic_recorder import mic_recorder
import av

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
if "video_bytes" not in st.session_state:
    st.session_state.video_bytes = None

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

# Video processor class
class VideoRecorder(VideoProcessorBase):
    def __init__(self):
        self.video_frames = []

    def recv(self, frame):
        self.video_frames.append(frame.to_ndarray(format="bgr24"))
        return frame

    def get_video_bytes(self):
        try:
            output = io.BytesIO()
            container = av.open(output, mode="w", format="mp4")
            video_stream = container.add_stream("h264", rate=30)
            video_stream.width = 640
            video_stream.height = 480

            for frame in self.video_frames:
                frame = av.VideoFrame.from_ndarray(frame, format="bgr24")
                for packet in video_stream.encode(frame):
                    container.mux(packet)

            for packet in video_stream.encode():
                container.mux(packet)

            container.close()
            return output.getvalue()
        except Exception as e:
            st.error(f"Error encoding video: {e}")
            return None

# Streamlit UI
st.title("Interview Practice App")

# Start recording
ctx = webrtc_streamer(
    key="interview-recorder",
    video_processor_factory=VideoRecorder,
    rtc_configuration=RTCConfiguration({
        "iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]
    }),
    media_stream_constraints={"video": True, "audio": False}  # Only video
)

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

        if ctx.video_processor:
            st.session_state.video_bytes = ctx.video_processor.get_video_bytes()

        st.session_state.question_index += 1
        if os.path.exists(audio_file):
            os.remove(audio_file)
        st.rerun()

# Interview completed
if st.session_state.question_index >= len(QUESTIONS):
    st.subheader("Interview completed!")
    for item in st.session_state.transcriptions:
        st.write(f"**Question:** {item['question']}")
        st.write(f"**Your Answer:** {item['transcription']}")
        st.write(f"**Timestamp:** {item['timestamp']}")
        st.write("---")

    if st.session_state.video_bytes:
        st.subheader("Video Recording")
        st.video(st.session_state.video_bytes)
        video_filename = f"interview_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        st.download_button("Download Video", st.session_state.video_bytes, video_filename, "video/mp4")

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
        st.session_state.video_bytes = None
        st.rerun()
