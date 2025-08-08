import streamlit as st
from streamlit_webrtc import webrtc_streamer, WebRtcMode
from aiortc.contrib.media import MediaRecorder
from pathlib import Path
import datetime
import time

st.set_page_config(page_title="Видео+аудио запись")
st.title("Запись видео с аудио (WebRTC → MP4)")

REC_DIR = Path("recordings")
REC_DIR.mkdir(exist_ok=True)

# создаём уникальное имя на сессию, чтобы файл не затирался при перерендерах
if "rec_filename" not in st.session_state:
    prefix = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    st.session_state.rec_filename = REC_DIR / f"{prefix}.mp4"

out_path = st.session_state.rec_filename

def in_recorder_factory():
    # MP4 даёт совместимость с Safari/iOS/Windows плеерами
    # aiortc перекодирует вход (VP8/Opus) в H.264/AAC
    return MediaRecorder(str(out_path), format="mp4")

ctx = webrtc_streamer(
    key="rec",
    mode=WebRtcMode.SENDRECV,
    media_stream_constraints={"video": True, "audio": True},
    in_recorder_factory=in_recorder_factory,
)

st.info("Нажмите Stop в виджете выше, чтобы завершить запись и финализировать файл.", icon="ℹ️")

# Показываем видео ТОЛЬКО когда запись остановлена и файл реально финализирован
def file_ready(p: Path) -> bool:
    if not p.exists():
        return False
    # иногда файл создаётся, но ещё пустой/без moov atom
    return p.stat().st_size > 100_000  # порог на всякий случай

if ctx and not ctx.state.playing:
    # даём долю секунды на финализацию файла
    for _ in range(10):
        if file_ready(out_path):
            break
        time.sleep(0.2)

    if file_ready(out_path):
        st.subheader("Просмотр записи (MP4)")
        st.video(str(out_path))
        st.download_button(
            "Скачать (MP4)",
            data=out_path.read_bytes(),
            file_name=out_path.name,
            mime="video/mp4",
        )
    else:
        st.warning("Запись ещё финализируется… Закройте/остановите поток и подождите 1–2 секунды.")