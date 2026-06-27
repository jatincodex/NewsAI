import os
import math
import struct
import wave
import logging
import textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from gtts import gTTS

try:
    from moviepy.editor import ImageClip, AudioFileClip
except ImportError:
    try:
        from moviepy import ImageClip, AudioFileClip
    except ImportError:
        ImageClip, AudioFileClip = None, None

logger = logging.getLogger(__name__)

class VideoSynthesisEngine:
    @staticmethod
    def create_silent_wav(output_path: str, duration_sec: float = 5.0):
        """Generates a silent WAV file using the standard python wave module as a fallback."""
        sample_rate = 44100
        num_samples = int(sample_rate * duration_sec)
        with wave.open(output_path, 'wb') as wav_file:
            # 1 channel, 2 bytes/sample (16-bit), sample_rate, num_samples, 'NONE', 'not compressed'
            wav_file.setparams((1, 2, sample_rate, num_samples, 'NONE', 'not compressed'))
            silent_data = struct.pack('<h', 0) * num_samples
            wav_file.writeframes(silent_data)

    @staticmethod
    def generate_audio_gtts(text: str, output_path: str) -> float:
        """
        Attempts to generate speech audio via gTTS.
        Returns the duration of the audio clip, falling back to silent audio on error.
        """
        try:
            logger.info("Attempting to generate narration audio via gTTS...")
            tts = gTTS(text=text, lang='en')
            tts.save(output_path)
            
            # Retrieve duration
            if AudioFileClip:
                with AudioFileClip(output_path) as audio:
                    return audio.duration
            return 5.0  # Default fallback duration
        except Exception as e:
            logger.warning(f"gTTS or AudioFileClip failed ({e}). Falling back to silent audio.")
            VideoSynthesisEngine.create_silent_wav(output_path, 5.0)
            return 5.0

    @staticmethod
    def generate_gradient_background(width: int, height: int, output_path: str):
        """Draws a premium purple-to-blue linear gradient background."""
        image = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(image)
        
        start_color = (26, 15, 46)  # Deep purple
        end_color = (13, 27, 42)    # Dark slate blue
        
        for y in range(height):
            r = int(start_color[0] + (end_color[0] - start_color[0]) * y / height)
            g = int(start_color[1] + (end_color[1] - start_color[1]) * y / height)
            b = int(start_color[2] + (end_color[2] - start_color[2]) * y / height)
            draw.line([(0, y), (width, y)], fill=(r, g, b))
            
        image.save(output_path)

    @staticmethod
    def render_text_frame(bg_path: str, text: str, output_path: str, width: int = 720, height: int = 1280):
        """Wraps and overlays news text centered on the background with drop shadows."""
        img = Image.open(bg_path)
        draw = ImageDraw.Draw(img)
        
        wrapped_lines = textwrap.wrap(text, width=25)
        wrapped_text = "\n".join(wrapped_lines)
        
        font = None
        font_sizes = [40, 36, 30]
        
        for size in font_sizes:
            try:
                font = ImageFont.truetype("arial.ttf", size)
                break
            except IOError:
                try:
                    font = ImageFont.truetype("calibri.ttf", size)
                    break
                except IOError:
                    continue
                    
        if not font:
            font = ImageFont.load_default()

        try:
            bbox = draw.textbbox((0, 0), wrapped_text, font=font)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
        except AttributeError:
            w, h = draw.textsize(wrapped_text, font=font) if hasattr(draw, "textsize") else (400, 200)

        x = (width - w) / 2
        y = (height - h) / 2

        header_text = "— NEWS AI VIBE —"
        try:
            h_bbox = draw.textbbox((0, 0), header_text, font=font)
            hw = h_bbox[2] - h_bbox[0]
        except AttributeError:
            hw = draw.textsize(header_text, font=font)[0] if hasattr(draw, "textsize") else 200
            
        draw.text(((width - hw) / 2, y - 120), header_text, fill=(0, 200, 255), font=font)

        draw.text((x + 2, y + 2), wrapped_text, fill=(0, 0, 0), font=font, align="center")
        draw.text((x, y), wrapped_text, fill=(255, 255, 255), font=font, align="center")
        
        img.save(output_path)

    @classmethod
    def generate_static_post_image(cls, text: str, output_path: str, width: int = 1080, height: int = 1080):
        """Generates a premium square (1:1) fact-checked post card image for main feed."""
        image = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(image)
        
        # 1. Gradient Background
        start_color = (26, 15, 46)  # Deep purple
        end_color = (13, 27, 42)    # Dark slate blue
        for y in range(height):
            r = int(start_color[0] + (end_color[0] - start_color[0]) * y / height)
            g = int(start_color[1] + (end_color[1] - start_color[1]) * y / height)
            b = int(start_color[2] + (end_color[2] - start_color[2]) * y / height)
            draw.line([(0, y), (width, y)], fill=(r, g, b))
            
        # 2. Draw styled borders
        border_margin = 60
        draw.rectangle(
            [(border_margin, border_margin), (width - border_margin, height - border_margin)],
            outline=(255, 255, 255, 20),
            width=2
        )
        draw.rectangle(
            [(border_margin + 8, border_margin + 8), (width - border_margin - 8, height - border_margin - 8)],
            outline=(0, 240, 255, 30),
            width=1
        )
        
        # Fonts
        font = None
        font_header = None
        for size in [40, 36, 30]:
            try:
                font = ImageFont.truetype("arial.ttf", size)
                font_header = ImageFont.truetype("arial.ttf", size + 6)
                break
            except:
                try:
                    font = ImageFont.truetype("calibri.ttf", size)
                    font_header = ImageFont.truetype("calibri.ttf", size + 6)
                    break
                except:
                    continue
        if not font:
            font = ImageFont.load_default()
            font_header = ImageFont.load_default()
            
        # Wrap text
        wrapped_lines = textwrap.wrap(text, width=35)
        wrapped_text = "\n".join(wrapped_lines)
        
        try:
            bbox = draw.textbbox((0, 0), wrapped_text, font=font)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
        except:
            w, h = draw.textsize(wrapped_text, font=font) if hasattr(draw, "textsize") else (600, 300)
            
        x = (width - w) / 2
        y = (height - h) / 2
        
        # Header: "NEWS AI"
        header_text = "— NEWS AI VERIFIED —"
        try:
            hw = draw.textbbox((0, 0), header_text, font=font_header)[2]
        except:
            hw = draw.textsize(header_text, font=font_header)[0] if hasattr(draw, "textsize") else 320
        draw.text(((width - hw) / 2, border_margin + 60), header_text, fill=(0, 240, 255), font=font_header)
        
        # Text Drop Shadow
        draw.text((x + 2, y + 2), wrapped_text, fill=(0, 0, 0), font=font, align="center")
        # Main Text
        draw.text((x, y), wrapped_text, fill=(255, 255, 255), font=font, align="center")
        
        # Verified Badge
        stamp_text = "✓ VERIFIED SOURCE"
        draw.rectangle(
            [(width/2 - 180, height - border_margin - 110), (width/2 + 180, height - border_margin - 50)],
            fill=(0, 50, 20),
            outline=(0, 255, 135),
            width=2
        )
        try:
            sw = draw.textbbox((0, 0), stamp_text, font=font)[2]
        except:
            sw = draw.textsize(stamp_text, font=font)[0] if hasattr(draw, "textsize") else 240
        draw.text(((width - sw) / 2, height - border_margin - 98), stamp_text, fill=(0, 255, 135), font=font)
        
        image.save(output_path)
        logger.info(f"Static image post card rendered successfully at {output_path}")

    @classmethod
    def synthesize_reel(cls, text: str, output_mp4_path: str) -> str:
        """
        Creates a vertical 9:16 video reel from the provided text.
        Combines PIL gradient rendering, text wrapping, speech audio, and MoviePy compilation.
        Returns the path to the completed MP4.
        """
        if not ImageClip or not AudioFileClip:
            error_msg = "MoviePy could not be imported; video synthesis aborted."
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        temp_dir = Path(output_mp4_path).parent / "temp"
        temp_dir.mkdir(exist_ok=True)
        
        audio_path = str(temp_dir / "audio.mp3")
        bg_path = str(temp_dir / "bg.png")
        frame_path = str(temp_dir / "frame.png")

        try:
            duration = cls.generate_audio_gtts(text, audio_path)
            duration = max(3.0, duration)
            
            cls.generate_gradient_background(720, 1280, bg_path)
            cls.render_text_frame(bg_path, text, frame_path, 720, 1280)
            
            logger.info("Compiling video reel with MoviePy...")
            clip = ImageClip(frame_path)
            
            if hasattr(clip, "with_duration"):
                clip = clip.with_duration(duration)
            else:
                clip = clip.set_duration(duration)
                
            audio = AudioFileClip(audio_path)
            
            if hasattr(clip, "with_audio"):
                clip = clip.with_audio(audio)
            else:
                clip = clip.set_audio(audio)

            clip.write_videofile(
                output_mp4_path,
                fps=24,
                codec="libx264",
                audio_codec="aac",
                logger=None
            )
            
            audio.close()
            clip.close()
            
            logger.info(f"Reel successfully synthesized at {output_mp4_path}")
            return output_mp4_path
            
        finally:
            for path in [audio_path, bg_path, frame_path]:
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except Exception as ex:
                    logger.warning(f"Failed to delete temp file {path}: {ex}")
            try:
                if temp_dir.exists():
                    temp_dir.rmdir()
            except:
                pass
