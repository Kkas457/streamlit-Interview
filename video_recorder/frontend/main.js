let mediaRecorder;
let recordedChunks = [];
let stream;

const video = document.getElementById("preview");

navigator.mediaDevices.getUserMedia({ video: true, audio: true }).then(userStream => {
    stream = userStream;
    video.srcObject = stream;
});

function startRecording() {
    recordedChunks = [];
    mediaRecorder = new MediaRecorder(stream);

    mediaRecorder.ondataavailable = e => {
        if (e.data.size > 0) recordedChunks.push(e.data);
    };

    mediaRecorder.onstop = () => {
        const blob = new Blob(recordedChunks, { type: "video/webm" });
        recordedChunks = [];

        blob.arrayBuffer().then(buffer => {
            const base64 = btoa(String.fromCharCode(...new Uint8Array(buffer)));
            const data = { video_data: base64 };
            window.streamlit.setComponentValue(data);
        });
    };

    mediaRecorder.start();
}

function stopRecording() {
    mediaRecorder.stop();
}
