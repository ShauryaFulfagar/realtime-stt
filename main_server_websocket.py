import os
import json
import uuid
import wave
import asyncio
import websockets
from pyannote.audio import Model
from pyannote.audio.pipelines import VoiceActivityDetection
from transformers import pipeline
import Keys_Tokens


class Client:
    def __init__(self, client_id, sampling_rate, samples_width):
        self.client_id = client_id
        self.buffer = bytearray()
        self.scratch_buffer = bytearray()
        self.config = {"language": None, "processing_strategy": "silence_at_end_of_chunk",
                       "processing_args": {"chunk_length_seconds": 2.25, "chunk_offset_seconds": 0.05}}
        self.file_counter = 0
        self.total_samples = 0
        self.sampling_rate = sampling_rate
        self.samples_width = samples_width

    def append_audio_data(self, audio_data):
        self.buffer.extend(audio_data)
        self.total_samples += len(audio_data) / self.samples_width

    def clear_buffer(self):
        self.buffer.clear()

    def increment_file_counter(self):
        self.file_counter += 1

    def get_file_name(self):
        return f"{self.client_id}_{self.file_counter}.wav"

    def update_config(self, config):
        if 'language' in config:
            self.config['language'] = config['language']
        if 'processing_strategy' in config:
            self.config['processing_strategy'] = config['processing_strategy']
        if 'processing_args' in config:
            self.config['processing_args'].update(config['processing_args'])


class PyannoteVAD:
    def __init__(self, auth_token):
        self.model = Model.from_pretrained(
            "pyannote/segmentation",
            use_auth_token=auth_token
        )
        self.vad_pipeline = VoiceActivityDetection(segmentation=self.model)
        self.vad_pipeline.instantiate({
            "onset": 0.5,
            "offset": 0.5,
            "min_duration_on": 0.1,
            "min_duration_off": 0.1
        })

    async def detect_activity(self, client):
        file_path = await save_audio_to_file(client.scratch_buffer, client.get_file_name())
        vad_results = self.vad_pipeline(file_path)
        os.remove(file_path)
        return [{"start": segment.start, "end": segment.end}
                for segment in vad_results.itersegments()]


class WhisperASR:
    def __init__(self):
        self.asr_pipeline = pipeline(
            "automatic-speech-recognition",
            model="openai/whisper-base",
        )

    async def transcribe(self, client):
        try:
            file_path = await save_audio_to_file(client.scratch_buffer, client.get_file_name())
            result = self.asr_pipeline(file_path)
            os.remove(file_path)
            return {
                "text": result['text'].strip()
            }
        except Exception as e:
            print(f"Transcription error: {str(e)}")
            return {"text": ""}


async def save_audio_to_file(audio_data, file_name, audio_dir="audio_files"):
    os.makedirs(audio_dir, exist_ok=True)
    file_path = os.path.join(audio_dir, file_name)
    with wave.open(file_path, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(audio_data)
    return file_path


async def process_audio(client, websocket, vad_pipeline, asr_pipeline):
    required_bytes = int(client.config['processing_args']['chunk_length_seconds'] *
                         client.sampling_rate * client.samples_width)

    if len(client.buffer) >= required_bytes:
        client.scratch_buffer.extend(client.buffer)
        client.buffer.clear()

        vad_results = await vad_pipeline.detect_activity(client)
        print(f"VAD results for {client.client_id}: {vad_results}")

        if vad_results:
            transcription = await asr_pipeline.transcribe(client)
            if transcription['text']:
                print(f"Sending transcription: {transcription['text']}")
                await websocket.send(json.dumps(transcription))

        client.scratch_buffer.clear()
        client.increment_file_counter()


async def handle_client(websocket, vad_pipeline, asr_pipeline, sampling_rate=16000, samples_width=2):
    client_id = str(uuid.uuid4())
    client = Client(client_id, sampling_rate, samples_width)
    print(f"Client {client_id} connected")

    try:
        async for message in websocket:
            if isinstance(message, bytes):
                client.append_audio_data(message)
                await process_audio(client, websocket, vad_pipeline, asr_pipeline)
            elif isinstance(message, str):
                try:
                    config = json.loads(message)
                    if config.get('type') == 'config':
                        client.update_config(config['data'])
                except json.JSONDecodeError:
                    print(f"Invalid JSON from {client_id}")
    except websockets.ConnectionClosed:
        print(f"Client {client_id} disconnected")


async def main():
    vad_pipeline = PyannoteVAD(Keys_Tokens.auth_token)
    asr_pipeline = WhisperASR()

    async with websockets.serve(
        lambda ws: handle_client(ws, vad_pipeline, asr_pipeline),
        "localhost", 8765
    ):
        print("Server started at ws://localhost:8765")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
