let websocket;
let mediaStream;
let audioContext;
let processor;
let isRecording = false;

// Initialize WebSocket connection
function initWebSocket() {
    websocket = new WebSocket("ws://localhost:8765");

    websocket.onopen = () => {
        console.log("WebSocket connected");
        const wsStatus = document.getElementById("wsStatus");
        wsStatus.textContent = "Connected";
        wsStatus.className = "connected";
        document.getElementById("startBtn").disabled = false;
    };

    websocket.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.text) {
                console.log("Received transcription:", data.text);
                const box = document.getElementById("transcriptionBox");
                box.textContent += ` ${data.text}`;
                box.scrollTop = box.scrollHeight;
            }
        } catch (error) {
            console.error("Error parsing message:", error);
        }
    };

    websocket.onclose = () => {
        const wsStatus = document.getElementById("wsStatus");
        wsStatus.textContent = "Disconnected";
        wsStatus.className = "disconnected";
        document.getElementById("startBtn").disabled = true;
        document.getElementById("stopBtn").disabled = true;

        // Make sure to remove active state and recording indicator
        const startBtn = document.getElementById("startBtn");
        startBtn.classList.remove("active");
        startBtn.innerHTML =
            '<i class="fa-solid fa-microphone"></i> Start Recording';
    };
}

async function startRecording() {
    if (isRecording) return;

    try {
        mediaStream = await navigator.mediaDevices.getUserMedia({
            audio: true,
        });
        audioContext = new AudioContext();
        const source = audioContext.createMediaStreamSource(mediaStream);

        processor = audioContext.createScriptProcessor(4096, 1, 1);
        source.connect(processor);
        processor.connect(audioContext.destination);

        processor.onaudioprocess = (e) => {
            if (!websocket || websocket.readyState !== WebSocket.OPEN) return;

            const audioData = convertFloat32ToInt16(
                downsampleBuffer(
                    e.inputBuffer.getChannelData(0),
                    audioContext.sampleRate,
                    16384
                )
            );
            websocket.send(audioData);
        };

        // Send configuration
        websocket.send(
            JSON.stringify({
                type: "config",
                data: {
                    processing_args: {
                        chunk_length_seconds: 2.25,
                        chunk_offset_seconds: 0.05,
                    },
                },
            })
        );

        isRecording = true;
        document.getElementById("stopBtn").disabled = false;

        // Apply pressed effect and add recording indicator
        const startBtn = document.getElementById("startBtn");
        startBtn.disabled = true;
        startBtn.classList.add("active");
        startBtn.innerHTML =
            '<span class="recording-indicator"></span><i class="fa-solid fa-microphone"></i> Recording...';
    } catch (error) {
        console.error("Error starting recording:", error);
    }
}

function stopRecording() {
    if (!isRecording) return;

    if (mediaStream)
        mediaStream.getTracks().forEach((track) => track.stop());
    if (processor) processor.disconnect();
    if (audioContext) audioContext.close();

    isRecording = false;

    // Remove pressed effect and recording indicator
    const startBtn = document.getElementById("startBtn");
    startBtn.disabled = false;
    startBtn.classList.remove("active");
    startBtn.innerHTML =
        '<i class="fa-solid fa-microphone"></i> Start Recording';

    document.getElementById("stopBtn").disabled = true;
}

// Audio processing utilities
function downsampleBuffer(buffer, inputRate, outputRate) {
    const ratio = inputRate / outputRate;
    const newLength = Math.round(buffer.length / ratio);
    const result = new Float32Array(newLength);

    for (let i = 0; i < newLength; i++) {
        result[i] = buffer[Math.round(i * ratio)];
    }
    return result;
}

function convertFloat32ToInt16(buffer) {
    const int16Buffer = new Int16Array(buffer.length);
    for (let i = 0; i < buffer.length; i++) {
        int16Buffer[i] = Math.min(1, buffer[i]) * 0x7fff;
    }
    return int16Buffer.buffer;
}

// Initialize when page loads
window.onload = initWebSocket;
