#!/usr/bin/env python3
"""
process_derja_audio.py
----------------------
Automatise le téléchargement et le traitement des audios depuis les résultats
du scraper ninja-derja (fichiers .jsonl).

Fonctionnalités :
  - Télécharge les MP3 via requests (avec headers navigateur pour éviter blocage)
  - Utilise ffmpeg directement (subprocess) pour l'extraction → WAV robuste
  - Extrait uniquement la région "term" (le mot seul, sans la phrase)
  - Filtre exact : term_arabic == query (ignore les expressions composées)
  - Déduplique, trim silence, normalise le volume
  - Génère manifest.txt prêt pour l'entraînement TTS
  - NOUVEAU : WebRTC VAD ou Silero VAD pour gérer les répétitions (3x le même mot)

Usage :
  python process_derja_audio.py --input results.jsonl --output_dir audio_output --vad-mode webrtc
  python process_derja_audio.py --input results.jsonl --output_dir audio_output --vad-mode silero
  python process_derja_audio.py --input results.jsonl --output_dir audio_output --vad-mode pydub

Dépendances :
  pip install requests pydub
  # Option 1 (Windows friendly): pip install webrtcvad-wheels
  # Option 2 (Meilleur): pip install torch torchaudio
  ffmpeg installé sur le système (dans le PATH)
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Dépendances Python
# ---------------------------------------------------------------------------
try:
    import requests
except ImportError:
    sys.exit("❌  requests manquant : pip install requests")

try:
    from pydub import AudioSegment
    from pydub.silence import detect_leading_silence, detect_nonsilent
except ImportError:
    sys.exit("❌  pydub manquant : pip install pydub")

# WebRTC VAD (optionnel)
try:
    import webrtcvad
    WEBRTCVAD_AVAILABLE = True
except ImportError:
    WEBRTCVAD_AVAILABLE = False

# Silero VAD (optionnel, meilleur mais nécessite torch)
try:
    import torch
    import torchaudio
    SILERO_AVAILABLE = True
except ImportError:
    SILERO_AVAILABLE = False

# pyloudnorm optionnel
try:
    import pyloudnorm as pyln
    import numpy as np
    LUFS_AVAILABLE = True
except ImportError:
    LUFS_AVAILABLE = False

# ---------------------------------------------------------------------------
# Vérification ffmpeg
# ---------------------------------------------------------------------------
def check_ffmpeg():
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False

# ---------------------------------------------------------------------------
# Paramètres
# ---------------------------------------------------------------------------
TARGET_SR        = 22050
TARGET_CHANNELS  = 1
TARGET_PEAK_DBFS = -3.0
TARGET_LUFS      = -23.0
SILENCE_THRESH   = -40
SILENCE_PADDING  = 100   # ms gardés en bord après trim
MIN_DURATION_MS  = 300
DOWNLOAD_TIMEOUT = 20
RETRY_ATTEMPTS   = 3
RETRY_DELAY      = 2
VAD_FRAME_MS     = 30    # 10, 20 ou 30ms pour WebRTC
VAD_AGGRESSIVE   = 2     # 0-3 (3 = très aggressif)

# Headers imitant un navigateur
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "audio/webm,audio/ogg,audio/*;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Referer": "https://derja.ninja/",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sanitize_filename(text: str) -> str:
    safe = re.sub(r'[^\w\u0600-\u06FF\u0750-\u077F]+', '_', text, flags=re.UNICODE)
    return safe.strip('_')[:80] or "unknown"


def download_audio(url: str, dest_path: str) -> bool:
    """Télécharge un fichier audio avec headers navigateur et retry."""
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            resp = requests.get(
                url,
                headers=BROWSER_HEADERS,
                timeout=DOWNLOAD_TIMEOUT,
                stream=True,
            )
            resp.raise_for_status()

            content = resp.content
            if len(content) < 1000:
                print(f"    ⚠️  Réponse trop petite ({len(content)} octets) — possible blocage")
                if attempt < RETRY_ATTEMPTS:
                    time.sleep(RETRY_DELAY)
                    continue
                return False

            with open(dest_path, 'wb') as f:
                f.write(content)

            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                 dest_path],
                capture_output=True, text=True,
            )
            if probe.returncode != 0 or not probe.stdout.strip():
                print(f"    ⚠️  ffprobe : fichier non lisible (tentative {attempt})")
                os.remove(dest_path)
                if attempt < RETRY_ATTEMPTS:
                    time.sleep(RETRY_DELAY)
                    continue
                return False

            return True

        except requests.RequestException as e:
            print(f"    ⚠️  Tentative {attempt}/{RETRY_ATTEMPTS} : {e}")
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_DELAY)
    return False


def extract_with_ffmpeg(src: str, dest_wav: str, start_s: float, end_s: float) -> bool:
    duration = max(0.1, end_s - start_s)
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_s),
        "-t",  str(duration),
        "-analyzeduration", "10000000",
        "-probesize", "10000000",
        "-i", src,
        "-ac", str(TARGET_CHANNELS),
        "-ar", str(TARGET_SR),
        "-acodec", "pcm_s16le",
        "-err_detect", "ignore_err",
        dest_wav,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        lines = [l for l in result.stderr.splitlines()
                 if any(k in l for k in ("Error", "Invalid", "failed", "Conversion"))]
        print(f"    ⚠️  ffmpeg error : {lines[-1] if lines else 'voir stderr'}")
        return False
    return os.path.exists(dest_wav) and os.path.getsize(dest_wav) > 0


def trim_silence(audio: AudioSegment) -> AudioSegment:
    """Trim classique avec pydub."""
    start_trim = detect_leading_silence(audio, silence_threshold=SILENCE_THRESH)
    end_trim   = detect_leading_silence(audio.reverse(), silence_threshold=SILENCE_THRESH)
    duration   = len(audio)
    s = max(0, start_trim - SILENCE_PADDING)
    e = max(s, duration - end_trim + SILENCE_PADDING)
    return audio[s:e]


def extract_single_repetition_pydub(audio, min_silence_len=500, keep="first"):
    """
    Détecte les répétitions via détection de silence long (pydub).
    Garde seulement la première.
    """
    ranges = detect_nonsilent(audio, min_silence_len=min_silence_len, 
                              silence_threshold=SILENCE_THRESH)
    
    if len(ranges) <= 1:
        return trim_silence(audio)
    
    print(f"    🔍  {len(ranges)} répétitions détectées (pydub), sélection: {keep}")
    
    if keep == "first":
        start, end = ranges[0]
    elif keep == "last":
        start, end = ranges[-1]
    elif keep == "middle":
        idx = len(ranges) // 2
        start, end = ranges[idx]
    elif keep == "longest":
        start, end = max(ranges, key=lambda x: x[1] - x[0])
    else:
        start, end = ranges[0]
    
    padding = 50
    start = max(0, start - padding)
    end = min(len(audio), end + padding)
    
    return audio[start:end]


def extract_first_repetition_webrtc(audio, aggressiveness=VAD_AGGRESSIVE, 
                                    padding_ms=100, min_duration_ms=200):
    """
    Utilise WebRTC VAD pour extraire UNIQUEMENT la première répétition.
    WebRTC nécessite 16kHz, 16-bit, mono.
    """
    if not WEBRTCVAD_AVAILABLE:
        print("    ⚠️  WebRTC VAD non dispo, fallback pydub")
        return extract_single_repetition_pydub(audio)
    
    # Conversion pour WebRTC
    audio_16k = (audio.set_frame_rate(16000)
                      .set_channels(1)
                      .set_sample_width(2))
    
    raw_data = audio_16k.raw_data
    vad = webrtcvad.Vad(aggressiveness)
    
    bytes_per_frame = int(16000 * VAD_FRAME_MS / 1000) * 2
    
    first_speech = bytearray()
    collecting = False
    silence_count = 0
    max_silence_frames = int(400 / VAD_FRAME_MS)  # 400ms de silence = fin
    
    for i in range(0, len(raw_data), bytes_per_frame):
        frame = raw_data[i:i+bytes_per_frame]
        if len(frame) < bytes_per_frame:
            break
        
        is_speech = vad.is_speech(frame, 16000)
        
        if is_speech:
            if not collecting:
                collecting = True
                silence_count = 0
            first_speech.extend(frame)
        else:
            if collecting:
                silence_count += 1
                if silence_count > max_silence_frames:
                    break
                if silence_count <= 2:
                    first_speech.extend(frame)
    
    if len(first_speech) < int(min_duration_ms * 16000 / 1000) * 2:
        print("    ⚠️  WebRTC: segment trop court, fallback pydub")
        return extract_single_repetition_pydub(audio)
    
    segment = AudioSegment(
        data=bytes(first_speech),
        sample_width=2,
        frame_rate=16000,
        channels=1
    )
    
    if padding_ms > 0:
        silence_pad = AudioSegment.silent(duration=padding_ms, frame_rate=16000)
        segment = silence_pad + segment + silence_pad
    
    if TARGET_SR != 16000:
        segment = segment.set_frame_rate(TARGET_SR)
    
    print(f"    ✅  WebRTC VAD: 1ère répétition ({len(segment)}ms)")
    return segment


def extract_first_repetition_silero(audio, padding_ms=100):
    """
    Utilise Silero VAD (meilleure qualité, nécessite torch).
    Détecte automatiquement les segments de parole.
    """
    if not SILERO_AVAILABLE:
        print("    ⚠️  Silero non dispo, fallback pydub")
        return extract_single_repetition_pydub(audio)
    
    # Charger le modèle Silero VAD
    model, utils = torch.hub.load(repo_or_dir='snakers4/silero-vad',
                                  model='silero_vad',
                                  force_reload=False,
                                  onnx=False)
    (get_speech_timestamps, _, read_audio, *_) = utils
    
    # Convertir en tensor torch à 16kHz
    audio_16k = audio.set_frame_rate(16000).set_channels(1)
    wav = torch.tensor(audio_16k.get_array_of_samples(), dtype=torch.float32) / 32768.0
    
    # Obtenir les timestamps
    speech_timestamps = get_speech_timestamps(wav, model, sampling_rate=16000, 
                                               min_silence_duration_ms=400)
    
    if not speech_timestamps:
        return extract_single_repetition_pydub(audio)
    
    # Prendre seulement le premier segment
    first = speech_timestamps[0]
    start_ms = int(first['start'] / 16)  # Convertir de samples à ms (16kHz)
    end_ms = int(first['end'] / 16)
    
    print(f"    ✅  Silero VAD: 1ère répétition détectée")
    
    # Extraire depuis l'audio original (qui est à TARGET_SR)
    start_orig = int(start_ms * TARGET_SR / 16000)
    end_orig = int(end_ms * TARGET_SR / 16000)
    
    segment = audio[start_orig:end_orig]
    
    if padding_ms > 0:
        silence = AudioSegment.silent(duration=padding_ms, frame_rate=TARGET_SR)
        segment = silence + segment + silence
    
    return segment


def normalize_audio(audio: AudioSegment) -> AudioSegment:
    if LUFS_AVAILABLE:
        samples = np.array(audio.get_array_of_samples(), dtype=np.float32)
        samples /= (2 ** (audio.sample_width * 8 - 1))
        meter = pyln.Meter(audio.frame_rate)
        try:
            loudness = meter.integrated_loudness(
                samples.reshape(-1, audio.channels) if audio.channels > 1 else samples
            )
            if loudness > -70:
                return audio.apply_gain(TARGET_LUFS - loudness)
        except Exception:
            pass
    if audio.dBFS > -float('inf'):
        return audio.apply_gain(TARGET_PEAK_DBFS - audio.dBFS)
    return audio

# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def process_jsonl(input_path, output_dir, region="term", normalization="peak", 
                  keep_raw=False, vad_mode="webrtc"):
    out     = Path(output_dir)
    wav_dir = out / "wav"
    tmp_dir = out / "_tmp_raw"
    wav_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    manifest_lines = []
    seen_terms     = {}
    stats = {"total": 0, "ok": 0, "dup": 0, "failed": 0, "short": 0}

    # Vérification VAD mode
    if vad_mode == "webrtc" and not WEBRTCVAD_AVAILABLE:
        print("⚠️  Mode WebRTC demandé mais librairie manquante. Fallback sur 'pydub'")
        vad_mode = "pydub"
    
    if vad_mode == "silero" and not SILERO_AVAILABLE:
        print("⚠️  Mode Silero demandé mais torch/torchaudio manquant. Fallback sur 'pydub'")
        vad_mode = "pydub"

    # Lecture JSONL
    entries = []
    with open(input_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"⚠️  Ligne JSON invalide : {e}")

    print(f"\n📂  {len(entries)} entrées — {input_path}")
    print(f"🎯  Région : '{region}' | VAD : '{vad_mode}' | Norm : {normalization.upper()}")
    print(f"📁  Sortie  : {output_dir}\n")

    for idx, entry in enumerate(entries, 1):
        stats["total"] += 1
        term_ar  = entry.get("term_arabic", "").strip()
        term_tr  = entry.get("term_transliteration", "").strip()
        query    = entry.get("query", "").strip()
        entry_id = entry.get("entry_id", f"entry_{idx}")
        url      = entry.get("audio", {}).get("source_url", "")
        regions  = entry.get("audio", {}).get("regions", {})

        print(f"[{idx}/{len(entries)}] {term_ar}  ({term_tr})")

        # ── Filtre exact query == term ────────────────────────────────────
        if query and term_ar != query:
            print(f"    ⏭️  Ignoré : '{term_ar}' ≠ query '{query}'")
            stats["dup"] += 1
            continue

        # ── Déduplication ─────────────────────────────────────────────────
        if term_ar in seen_terms:
            print(f"    ⏭️  Doublon, déjà traité.")
            stats["dup"] += 1
            continue

        if not url:
            print("    ❌  Pas d'URL audio.")
            stats["failed"] += 1
            continue

        # ── Région temporelle ─────────────────────────────────────────────
        region_data = regions.get(region)
        if not region_data:
            fallback = "sentence" if region == "term" else "term"
            region_data = regions.get(fallback)
            if region_data:
                print(f"    ⚠️  Région '{region}' absente → fallback '{fallback}'")
            else:
                print("    ❌  Aucune région audio disponible.")
                stats["failed"] += 1
                continue

        start_s = region_data.get("start", 0.0)
        end_s   = region_data.get("end",   0.0)

        # ── Téléchargement ────────────────────────────────────────────────
        raw_path = str(tmp_dir / f"{entry_id}.mp3")
        print(f"    ⬇️  {url}")
        if not download_audio(url, raw_path):
            print("    ❌  Téléchargement échoué.")
            stats["failed"] += 1
            continue

        # ── Extraction + conversion via ffmpeg ────────────────────────────
        safe_name    = sanitize_filename(term_ar or term_tr or entry_id)
        wav_filename = f"{safe_name}.wav"
        wav_path     = str(wav_dir / wav_filename)

        ctr = 1
        while wav_path in seen_terms.values():
            wav_filename = f"{safe_name}_{ctr}.wav"
            wav_path = str(wav_dir / wav_filename)
            ctr += 1

        print(f"    ✂️  Extraction [{start_s:.2f}s → {end_s:.2f}s]")
        if not extract_with_ffmpeg(raw_path, wav_path, start_s, end_s):
            print("    ❌  Extraction ffmpeg échouée.")
            stats["failed"] += 1
            if not keep_raw and os.path.exists(raw_path):
                os.remove(raw_path)
            continue

        # ── Post-traitement avec VAD ──────────────────────────────────────
        try:
            clip = AudioSegment.from_wav(wav_path)

            # Sélection de la méthode de détection des répétitions
            if vad_mode == "webrtc":
                clip = extract_first_repetition_webrtc(clip)
            elif vad_mode == "silero":
                clip = extract_first_repetition_silero(clip)
            elif vad_mode == "pydub":
                clip = extract_single_repetition_pydub(clip, min_silence_len=500)
            else:  # none
                clip = trim_silence(clip)

            if len(clip) < MIN_DURATION_MS:
                print(f"    ⚠️  Trop court après VAD ({len(clip)}ms), ignoré.")
                stats["short"] += 1
                os.remove(wav_path)
                if not keep_raw:
                    os.remove(raw_path)
                continue

            # Normalisation volume
            clip = normalize_audio(clip)

            # Ré-export final
            clip.export(wav_path, format="wav")

            duration_s = len(clip) / 1000.0
            print(f"    ✅  {wav_filename}  ({duration_s:.2f}s)")

            seen_terms[term_ar] = wav_path
            transcript = term_ar if term_ar else term_tr
            manifest_lines.append(f"{wav_path}|{transcript}|speaker0")
            stats["ok"] += 1

        except Exception as e:
            print(f"    ❌  Erreur post-traitement : {e}")
            stats["failed"] += 1

        finally:
            if not keep_raw and os.path.exists(raw_path):
                os.remove(raw_path)

    # Nettoyage dossier tmp
    if not keep_raw:
        try:
            tmp_dir.rmdir()
        except OSError:
            pass

    # Manifest
    manifest_path = out / "manifest.txt"
    with open(manifest_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(manifest_lines))

    print(f"\n📋  Manifest : {manifest_path}  ({len(manifest_lines)} entrées)")
    print("\n" + "="*50)
    print("📊  RÉSUMÉ")
    print("="*50)
    print(f"  Total         : {stats['total']}")
    print(f"  ✅ Réussis    : {stats['ok']}")
    print(f"  ⏭️  Ignorés    : {stats['dup']}")
    print(f"  ⚠️  Trop courts : {stats['short']}")
    print(f"  ❌ Échecs      : {stats['failed']}")
    print("="*50)

    if not LUFS_AVAILABLE and normalization == "lufs":
        print("\n💡  pyloudnorm absent → Peak utilisé. pip install pyloudnorm numpy")

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    if not check_ffmpeg():
        sys.exit("❌  ffmpeg introuvable. Installe-le et assure-toi qu'il est dans le PATH.")

    parser = argparse.ArgumentParser(
        description="Télécharge et traite les audios ninja-derja (.jsonl)"
    )
    parser.add_argument("--input",  "-i", required=True, help="Fichier .jsonl")
    parser.add_argument("--output_dir", "-o", default="derja_audio_output")
    parser.add_argument("--region", "-r", choices=["term", "sentence"], default="term")
    parser.add_argument("--normalization", "-n", choices=["peak", "lufs"], default="peak")
    parser.add_argument("--vad-mode", choices=["none", "pydub", "webrtc", "silero"], 
                        default="pydub",
                        help="Méthode de détection des répétitions: "
                             "webrtc (rapide), silero (meilleur), pydub (sans dépendances), none")
    parser.add_argument("--keep_raw", action="store_true",
                        help="Conserver les MP3 bruts téléchargés")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        sys.exit(f"❌  Fichier introuvable : {args.input}")

    process_jsonl(
        input_path=args.input,
        output_dir=args.output_dir,
        region=args.region,
        normalization=args.normalization,
        keep_raw=args.keep_raw,
        vad_mode=args.vad_mode,
    )

if __name__ == "__main__":
    main()