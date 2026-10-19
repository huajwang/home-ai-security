#!/bin/bash
# Download speech models for the voice satellite.
# SenseVoice transcribes Chinese and English. Whisper tiny.en remains as a fallback.
# Piper voices speak the hub reply.
set -euo pipefail

ROOT="${1:-/home/radxa/home-ai-security}"
MODEL_DIR="$ROOT/models"
PIPER_DIR="$MODEL_DIR/piper"
WHISPER_DIR="$MODEL_DIR/sherpa-onnx-whisper-tiny.en"
SENSE_DIR="$MODEL_DIR/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"

WHISPER_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-whisper-tiny.en.tar.bz2"
SENSE_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2"
PIPER_ZH_URL="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx"
PIPER_ZH_JSON_URL="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx.json"

mkdir -p "$MODEL_DIR" "$PIPER_DIR"

download_tar() {
  local url="$1"
  local marker="$2"
  local name="$3"
  if [[ -f "$marker" ]]; then
    echo "$name already present"
    return
  fi
  local tmp
  tmp="$(mktemp -d)"
  echo "Downloading $name..."
  curl -L --fail --retry 3 -o "$tmp/model.tar.bz2" "$url"
  tar -xjf "$tmp/model.tar.bz2" -C "$MODEL_DIR"
  rm -rf "$tmp"
  echo "Installed $name"
}

download_tar "$WHISPER_URL" "$WHISPER_DIR/tiny.en-encoder.int8.onnx" "Whisper tiny.en"
download_tar "$SENSE_URL" "$SENSE_DIR/model.int8.onnx" "SenseVoice Chinese and English"

if [[ ! -f "$PIPER_DIR/en_US-lessac-medium.onnx" ]]; then
  echo "English Piper voice is missing: $PIPER_DIR/en_US-lessac-medium.onnx" >&2
  exit 1
fi
echo "English Piper voice present."

if [[ ! -f "$PIPER_DIR/zh_CN-huayan-medium.onnx" || ! -f "$PIPER_DIR/zh_CN-huayan-medium.onnx.json" ]]; then
  echo "Downloading Chinese Piper voice..."
  curl -L --fail --retry 3 -o "$PIPER_DIR/zh_CN-huayan-medium.onnx" "$PIPER_ZH_URL"
  curl -L --fail --retry 3 -o "$PIPER_DIR/zh_CN-huayan-medium.onnx.json" "$PIPER_ZH_JSON_URL"
fi
echo "Chinese Piper voice present."
