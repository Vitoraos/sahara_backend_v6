from typing import Protocol
import collections
import numpy as np


class VAD(Protocol):
    async def is_speech(self, audio: bytes) -> bool:
        ...


class VADStub:
    """Voice Activity Detection stub.
    
    This stub raises NotImplementedError when called.
    VAD integration is not wired yet — the pipeline currently processes all audio
    without voice activity detection. For production use, implement a real VAD
    (e.g., using webrtcvad, silero-vad, or a cloud VAD service) and replace this stub.
    """
    
    async def is_speech(self, audio: bytes) -> bool:
        raise NotImplementedError('VAD integration is not wired yet.')


class WebrtcVAD:
    """Production-ready Voice Activity Detection using webrtcvad.
    
    This implementation uses the WebRTC VAD algorithm which is widely used
    in real-time communication systems. It provides accurate voice activity
    detection with low latency, making it suitable for voice agents.
    
    The VAD processes audio in 10ms, 20ms, or 30ms frames and returns a boolean
    indicating whether speech is detected in each frame.
    """
    
    def __init__(self, 
                 sample_rate: int = 16000,
                 mode: int = 2,
                 frame_duration_ms: int = 30) -> None:
        """
        Initialize the WebRTC VAD.
        
        Args:
            sample_rate: Audio sample rate in Hz (must be 8000, 16000, 32000, or 48000)
            mode: VAD aggressiveness (0-3), where 0 is least aggressive and 3 is most aggressive
            frame_duration_ms: Frame duration in milliseconds (must be 10, 20, or 30)
        """
        try:
            import webrtcvad
        except ImportError:
            raise ImportError(
                "webrtcvad package is required for WebrtcVAD. "
                "Install it with: pip install webrtcvad"
            )
        
        if sample_rate not in (8000, 16000, 32000, 48000):
            raise ValueError("Sample rate must be 8000, 16000, 32000, or 48000 Hz")
        
        if mode not in (0, 1, 2, 3):
            raise ValueError("Mode must be between 0 and 3")
        
        if frame_duration_ms not in (10, 20, 30):
            raise ValueError("Frame duration must be 10, 20, or 30 ms")
        
        self._sample_rate = sample_rate
        self._mode = mode
        self._frame_duration_ms = frame_duration_ms
        self._vad = webrtcvad.Vad(mode)
        self._frame_size = int(sample_rate * frame_duration_ms / 1000)
        self._bytes_per_sample = 2  # 16-bit PCM
        self._frame_size_bytes = self._frame_size * self._bytes_per_sample
        
        # For audio buffering to handle variable-sized chunks
        self._audio_buffer = b""
    
    async def is_speech(self, audio: bytes) -> bool:
        """
        Check if audio contains speech.
        
        This method buffers incoming audio and processes it in frames that match
        the VAD's expected frame size. It returns True if any frame in the
        buffered audio contains speech.
        
        Args:
            audio: Raw PCM16 audio bytes
            
        Returns:
            True if speech is detected, False otherwise
        """
        if not audio:
            return False
        
        # Add new audio to buffer
        self._audio_buffer += audio
        
        # Process complete frames from the buffer
        speech_detected = False
        
        while len(self._audio_buffer) >= self._frame_size_bytes:
            # Extract one frame
            frame = self._audio_buffer[:self._frame_size_bytes]
            self._audio_buffer = self._audio_buffer[self._frame_size_bytes:]
            
            # Check if frame contains speech
            if self._vad.is_speech(frame, self._sample_rate):
                speech_detected = True
                # We can break early if we just need to know if ANY speech is present
                break
        
        return speech_detected
    
    def reset(self) -> None:
        """Reset the VAD's internal buffer."""
        self._audio_buffer = b""


# Alternative: Simple energy-based VAD for environments where webrtcvad is not available
class SimpleEnergyVAD:
    """Simple energy-based VAD implementation.
    
    A basic Voice Activity Detection implementation using audio energy thresholds.
    This is a fallback option when webrtcvad is not available or suitable.
    For production use, consider using WebrtcVAD instead.
    """
    
    def __init__(self, energy_threshold: float = 500.0, sample_rate: int = 16000) -> None:
        self._energy_threshold = energy_threshold
        self._sample_rate = sample_rate
        self._audio_buffer = b""
        self._bytes_per_sample = 2  # 16-bit PCM
    
    async def is_speech(self, audio: bytes) -> bool:
        """Check if audio contains speech based on energy threshold."""
        if not audio:
            return False
        
        # Add new audio to buffer
        self._audio_buffer += audio
        
        # Process audio in chunks to avoid excessive memory usage
        # Process in 20ms chunks for consistency
        chunk_duration_ms = 20
        chunk_size = int(self._sample_rate * chunk_duration_ms / 1000) * self._bytes_per_sample
        
        speech_detected = False
        
        while len(self._audio_buffer) >= chunk_size:
            # Extract one chunk
            chunk = self._audio_buffer[:chunk_size]
            self._audio_buffer = self._audio_buffer[chunk_size:]
            
            # Convert to numpy array for energy calculation
            try:
                audio_np = np.frombuffer(chunk, dtype=np.int16)
                # Calculate normalized energy
                energy = np.sum(np.abs(audio_np)) / len(audio_np)
                
                if energy > self._energy_threshold:
                    speech_detected = True
                    break
            except Exception:
                # If numpy is not available or there's an error, fall back to simple method
                energy = sum(abs(b) for b in chunk) / len(chunk)
                if energy > self._energy_threshold:
                    speech_detected = True
                    break
        
        return speech_detected
    
    def reset(self) -> None:
        """Reset the VAD's internal buffer."""
        self._audio_buffer = b""
