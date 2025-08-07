import streamlit as st
import json
import os
from gtts import gTTS
import datetime
from openai import OpenAI
import io
import sounddevice as sd
import soundfile as sf
import numpy as np
from streamlit_webrtc import webrtc_streamer, VideoProcessorBase, RTCConfiguration
import av
import base64

# Initialize Open AI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Sample questions
QUESTIONS = [
    "Tell me about yourself.",
    "What are your strengths?",
    "Describe a challenging project you worked on.",
    "Why do you want this position?",
    "Where do you see yourself in five years?"
]

# Initialize session state
if 'question_index' not in st.session_state:
    st.session_state.question_index = 0
if 'transcriptions' not in st.session_state:
    st.session_state.transcriptions = []
if 'recording' not in st.session_state:
    st.session_state.recording = False
if 'audio_stream' not in st.session_state:
    st.session_state.audio_stream = None
if 'video_bytes' not in st.session_state:
    st.session_state.video_bytes = None

# Global variable to manage recording state
recording_state = {'is_recording': False, 'audio_buffer': []}

# Function to convert text to speech
def text_to_speech(text, filename):
    try:
        tts = gTTS(text=text, lang='en')
        tts.save(filename)
        return filename
    except Exception as e:
        st.error(f"Error generating audio: {e}")
        return None

# Function to transcribe audio using Open AI Whisper
def transcribe_audio(audio_data, sample_rate):
    try:
        temp_file = "temp_audio.wav"
        sf.write(audio_data, temp_file, sample_rate)
        
        with open(temp_file, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file
            )
        
        os.remove(temp_file)
        return transcription.text
    except Exception as e:
        st.error(f"Error transcribing audio: {e}")
        return "Transcription failed"

# Custom video processor for continuous recording
class VideoRecorder(VideoProcessorBase):
    def __init__(self):
        self.frames = []
    
    def recv(self, frame):
        self.frames.append(frame.to_ndarray(format="bgr24"))
        return frame
    
    def get_video_bytes(self):
        try:
            output = io.BytesIO()
            container = av.open(output, mode='w', format='mp4')
            stream = container.add_stream('h264', rate=30)
            stream.width = 640
            stream.height = 480
            
            for frame in self.frames:
                frame = av.VideoFrame.from_ndarray(frame, format='bgr24')
                for packet in stream.encode(frame):
                    container.mux(packet)
            
            for packet in stream.encode():
                container.mux(packet)
            
            container.close()
            return output.getvalue()
        except Exception as e:
            st.error(f"Error encoding video: {e}")
            return None

# Audio callback function
def audio_callback(indata, frames, time, status):
    if recording_state['is_recording']:
        recording_state['audio_buffer'].append(indata.copy())

# Main app
st.title("Interview Practice App")

# Start video recording
st.write("Video recording is active. Please ensure your webcam and microphone are enabled.")
ctx = webrtc_streamer(
    key="interview-recorder",
    video_processor_factory=VideoRecorder,
    rtc_configuration=RTCConfiguration({"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]}),
    media_stream_constraints={"video": True, "audio": True}
)

# Audio recording setup
sample_rate = 44100

# Display and play current question
if st.session_state.question_index < len(QUESTIONS):
    current_question = QUESTIONS[st.session_state.question_index]
    st.write(f"Question {st.session_state.question_index + 1}: {current_question}")
    
    # Generate and play audio for the question
    audio_file = f"question_{st.session_state.question_index}.mp3"
    if text_to_speech(current_question, audio_file):
        with open(audio_file, "rb") as f:
            audio_bytes = f.read()
        st.audio(audio_bytes, format="audio/mp3", autoplay=True)
    
    # Start audio recording
    if not st.session_state.recording:
        st.session_state.recording = True
        recording_state['is_recording'] = True
        recording_state['audio_buffer'] = []
        try:
            st.session_state.audio_stream = sd.InputStream(samplerate=sample_rate, channels=1, callback=audio_callback)
            st.session_state.audio_stream.start()
            st.write("Recording your response...")
        except Exception as e:
            st.error(f"Error starting audio recording: {e}")
    
    # Button to proceed
    button_label = "Finish" if st.session_state.question_index == len(QUESTIONS) - 1 else "Next"
    if st.button(button_label):
        # Stop and process audio recording
        if st.session_state.audio_stream:
            st.session_state.audio_stream.stop()
            st.session_state.audio_stream.close()
            st.session_state.audio_stream = None
        
        if recording_state['audio_buffer']:
            audio_data = np.concatenate(recording_state['audio_buffer'])
            transcription = transcribe_audio(audio_data, sample_rate)
            st.session_state.transcriptions.append({
                "question": current_question,
                "transcription": transcription,
                "timestamp": datetime.datetime.now().isoformat()
            })
            recording_state['audio_buffer'] = []
        
        # Save video if last question
        if st.session_state.question_index == len(QUESTIONS) - 1 and ctx.video_processor:
            st.session_state.video_bytes = ctx.video_processor.get_video_bytes()
        
        st.session_state.question_index += 1
        st.session_state.recording = False
        recording_state['is_recording'] = False
        if os.path.exists(audio_file):
            os.remove(audio_file)
        st.rerun()

# Display results and video after interview
if st.session_state.question_index >= len(QUESTIONS):
    st.write("Interview completed!")
    
    # Display transcriptions
    st.subheader("Your Responses")
    for item in st.session_state.transcriptions:
        st.write(f"**Question**: {item['question']}")
        st.write(f"**Response**: {item['transcription']}")
        st.write(f"**Timestamp**: {item['timestamp']}")
        st.write("---")
    
    # Save and display video
    if st.session_state.video_bytes:
        st.subheader("Video Recording")
        st.video(st.session_state.video_bytes)
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        video_filename = f"interview_{timestamp}.mp4"
        st.download_button(
            label="Download Video Recording",
            data=st.session_state.video_bytes,
            file_name=video_filename,
            mime="video/mp4"
        )
    
    # Save results to JSON
    results = {
        "interview_date": datetime.datetime.now().isoformat(),
        "questions": st.session_state.transcriptions
    }
    json_filename = f"interview_results_{timestamp}.json"
    with open(json_filename, "w") as f:
        json.dump(results, f, indent=2)
    
    with open(json_filename, "rb") as f:
        st.download_button(
            label="Download Results (JSON)",
            data=f,
            file_name=json_filename,
            mime="application/json"
        )
    
    # Reset button
    if st.button("Start New Interview"):
        st.session_state.question_index = 0
        st.session_state.transcriptions = []
        st.session_state.recording = False
        recording_state['is_recording'] = False
        st.session_state.audio_stream = None
        st.session_state.video_bytes = None
        st.rerun()